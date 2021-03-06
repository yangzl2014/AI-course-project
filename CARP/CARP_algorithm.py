import numpy as np
import random
from typing import Dict, Tuple
from copy import copy, deepcopy
import multiprocessing
import os

from CARP_info import CARPInfo, Edge, Solution, get_cost, get_costs


class CARPAlgorithm:
    def __init__(self, info, population_size=100, mutation_rate=0.2):
        """

        :type info: CARPInfo
        """
        self.info = info
        self.min_dist = info.min_dist
        self.depot = info.depot
        self.capacity = info.capacity
        self.tasks = info.tasks
        self.mutation_rate = mutation_rate

        self.move = [self.single_insertion, self.double_insertion, self.swap]

        from_depot = lambda x: self.min_dist[x, self.depot]
        self.rules = [
            lambda x, y, c: from_depot(x.v) > from_depot(y.v),
            lambda x, y, c: from_depot(x.v) < from_depot(y.v),
            lambda x, y, c: x.demand / x.cost > y.demand / y.cost,
            lambda x, y, c: x.demand / x.cost < y.demand / y.cost,
            lambda x, y, c: from_depot(x.v) > from_depot(y.v) if c < self.capacity / 2 else from_depot(x.v) < from_depot(y.v)
        ]

        self.population_size = population_size
        self.population = self.initialize()

    def path_scanning(self, rule):
        free: Dict[Tuple[int, int], Edge] = self.tasks.copy()
        routes, loads, costs = [], [], []
        while len(free):
            last_end = self.depot
            routes.append([])
            loads.append(0)
            costs.append(0)
            while len(free):
                selected_edge = list(free.values())[0]
                distance = np.inf
                for edge in [x for x in free.values() if loads[-1] + x.demand <= self.capacity]:
                    d = self.min_dist[last_end, edge.u]
                    if d < distance:
                        distance = d
                        selected_edge = edge
                    elif d == distance and self.better(edge, selected_edge, loads[-1], rule):
                        selected_edge = edge

                if distance == np.inf:  # means distance not updated
                    break

                routes[-1].append((selected_edge.u, selected_edge.v))
                free.pop((selected_edge.u, selected_edge.v))
                free.pop((selected_edge.v, selected_edge.u))

                loads[-1] += selected_edge.demand
                costs[-1] += selected_edge.cost + distance  # task_cost and min_dist cost

                last_end = selected_edge.v
            costs[-1] += self.min_dist[last_end, self.depot]

        solution = Solution(routes, loads, costs, sum(costs), self.capacity)

        return solution

    def initialize(self):
        population = set()

        # generate according to 5 rules
        for rule in self.rules:
            result = self.path_scanning(rule)
            population.add(result)

        origin_5 = copy(population)

        # extend to population_size
        while len(population) < self.population_size:
            for p in origin_5:
                moves = self.move
                new_solution: Solution = random.choice(moves)(p)
                if random.random() > new_solution.discard_prop:
                    population.add(new_solution)

        return population

    def get_best_ini(self):
        best_result = Solution.worst()
        for rule in self.rules:
            result = self.path_scanning(rule)
            if result.total_cost < best_result.total_cost:
                best_result = result

        return best_result

    def single_insertion(self, solution: Solution):
        # get selected task index
        new_solution = deepcopy(solution)
        routes: list = new_solution.routes
        selected_arc_index = random.randrange(0, len(routes))  # start <= N < end
        selected_arc = routes[selected_arc_index]

        selected_task_index = random.randrange(0, len(selected_arc))  # start <= N < end

        # information used in calculation
        u, v = selected_arc[selected_task_index]
        task = self.tasks[(u, v)]

        # calculate changed selected arc costs
        pre_end = selected_arc[selected_task_index - 1][1] if selected_task_index != 0 else self.depot
        next_start = selected_arc[selected_task_index + 1][0] if selected_task_index != len(selected_arc) - 1 else self.depot

        changed_cost = self.min_dist[pre_end, next_start] - self.min_dist[pre_end, u] - self.min_dist[v, next_start] - task.cost

        new_solution.costs[selected_arc_index] += changed_cost
        new_solution.total_cost += changed_cost
        new_solution.loads[selected_arc_index] -= task.demand

        selected_task = selected_arc.pop(selected_task_index)

        # get inserted index
        routes.append([])
        inserting_arc_index = random.randrange(0, len(routes))
        inserting_arc = routes[inserting_arc_index]
        inserting_position = random.randint(0, len(inserting_arc))  # start <= N <= end

        # calculate changed inserted arc costs
        pre_end = inserting_arc[inserting_position - 1][1] if inserting_position != 0 else self.depot
        next_start = inserting_arc[inserting_position][0] if inserting_position != len(inserting_arc) else self.depot

        changed_cost = self.min_dist[pre_end, u] + self.min_dist[v, next_start] + task.cost - self.min_dist[pre_end, next_start]
        reversed_changed_cost = self.min_dist[pre_end, v] + self.min_dist[u, next_start] + task.cost - self.min_dist[pre_end, next_start]  # (v, u)
        if reversed_changed_cost < changed_cost:
            selected_task = (v, u)
            changed_cost = reversed_changed_cost

        if not inserting_arc:  # means a new arc
            new_solution.costs.append(changed_cost)
            new_solution.loads.append(task.demand)
        else:
            del routes[-1]
            new_solution.costs[inserting_arc_index] += changed_cost
            new_solution.loads[inserting_arc_index] += task.demand
        new_solution.total_cost += changed_cost

        inserting_arc.insert(inserting_position, selected_task)

        new_solution.check_valid()

        return new_solution

    def double_insertion(self, solution):
        # get selected first task index
        new_solution = deepcopy(solution)
        routes: list = new_solution.routes
        selected_arc_index = random.randrange(0, len(routes))  # start <= N < end
        while len(routes[selected_arc_index]) < 2:  # routes that size >= 2 can be applied DI
            selected_arc_index = random.randrange(0, len(routes))

        selected_arc = routes[selected_arc_index]
        selected_task_index = random.randrange(0, len(selected_arc) - 1)  # start <= N < end - 1, should leave a position for second

        # information used in calculation
        u1, v1 = selected_arc[selected_task_index]
        u2, v2 = selected_arc[selected_task_index + 1]
        task1 = self.tasks[(u1, v1)]
        task2 = self.tasks[(u2, v2)]

        # calculate changed selected arc costs
        pre_end = selected_arc[selected_task_index - 1][1] if selected_task_index != 0 else self.depot
        next_start = selected_arc[selected_task_index + 2][0] if selected_task_index != len(selected_arc) - 2 else self.depot

        changed_cost = self.min_dist[pre_end, next_start] \
                       - self.min_dist[pre_end, u1] - task1.cost - self.min_dist[v1, u2] - task2.cost - self.min_dist[v2, next_start]
        new_solution.costs[selected_arc_index] += changed_cost
        new_solution.total_cost += changed_cost
        new_solution.loads[selected_arc_index] -= task1.demand + task2.demand

        selected_task1 = selected_arc.pop(selected_task_index)
        selected_task2 = selected_arc.pop(selected_task_index)

        # get inserted index
        routes.append([])
        inserting_arc_index = random.randrange(0, len(routes))
        inserting_arc = routes[inserting_arc_index]
        inserting_position = random.randint(0, len(inserting_arc))  # start <= N <= end

        # calculate changed inserted arc costs
        pre_end = inserting_arc[inserting_position - 1][1] if inserting_position != 0 else self.depot
        next_start = inserting_arc[inserting_position][0] if inserting_position != len(inserting_arc) else self.depot

        changed_cost = self.min_dist[pre_end, u1] + task1.cost + self.min_dist[v1, u2] + task2.cost + self.min_dist[v2, next_start] \
                       - self.min_dist[pre_end, next_start]
        reversed_changed_cost = self.min_dist[pre_end, v2] + task1.cost + self.min_dist[u2, v1] + task2.cost + self.min_dist[u1, next_start] \
                                - self.min_dist[pre_end, next_start]
        if reversed_changed_cost < changed_cost:
            selected_task1 = (v2, u2)
            selected_task2 = (v1, u1)
            changed_cost = reversed_changed_cost

        if not inserting_arc:  # means a new arc
            new_solution.costs.append(changed_cost)
            new_solution.loads.append(task1.demand + task2.demand)
        else:
            del routes[-1]
            new_solution.costs[inserting_arc_index] += changed_cost
            new_solution.loads[inserting_arc_index] += task1.demand + task2.demand
        new_solution.total_cost += changed_cost

        inserting_arc.insert(inserting_position, selected_task2)
        inserting_arc.insert(inserting_position, selected_task1)

        new_solution.check_valid()

        return new_solution

    def swap(self, solution):
        new_solution = deepcopy(solution)
        routes: list = new_solution.routes

        # get first selected task index
        selected_arc_index1 = random.randrange(0, len(routes))  # start <= N < end
        selected_arc1 = routes[selected_arc_index1]
        selected_task_index1 = random.randrange(0, len(selected_arc1))  # start <= N < end

        # get second selected task index
        selected_arc_index2 = random.randrange(0, len(routes))  # start <= N < end
        selected_arc2 = routes[selected_arc_index2]
        selected_task_index2 = random.randrange(0, len(selected_arc2))  # start <= N < end
        while selected_arc_index1 == selected_arc_index2 and selected_task_index1 == selected_task_index2:
            selected_arc_index2 = random.randrange(0, len(routes))  # start <= N < end
            selected_arc2 = routes[selected_arc_index2]
            selected_task_index2 = random.randrange(0, len(selected_arc2))  # start <= N < end

        # information used in calculation
        u1, v1 = selected_arc1[selected_task_index1]
        u2, v2 = selected_arc2[selected_task_index2]
        task1 = self.tasks[(u1, v1)]
        task2 = self.tasks[(u2, v2)]

        pre_end1 = selected_arc1[selected_task_index1 - 1][1] if selected_task_index1 != 0 else self.depot
        next_start1 = selected_arc1[selected_task_index1 + 1][0] if selected_task_index1 != len(selected_arc1) - 1 else self.depot
        pre_end2 = selected_arc2[selected_task_index2 - 1][1] if selected_task_index2 != 0 else self.depot
        next_start2 = selected_arc2[selected_task_index2 + 1][0] if selected_task_index2 != len(selected_arc2) - 1 else self.depot

        selected_task1 = selected_arc1.pop(selected_task_index1)
        if selected_arc_index1 == selected_arc_index2 and selected_task_index1 < selected_task_index2:
            selected_task2 = selected_arc2.pop(selected_task_index2 - 1)
        else:
            selected_task2 = selected_arc2.pop(selected_task_index2)

        # first arc cost change : insert task2 into arc1
        reduced_cost1 = self.min_dist[pre_end1, u1] + task1.cost + self.min_dist[v1, next_start1]
        changed_cost1 = self.min_dist[pre_end1, u2] + task2.cost + self.min_dist[v2, next_start1] - reduced_cost1
        reversed_changed_cost1 = self.min_dist[pre_end1, v2] + task2.cost + self.min_dist[u2, next_start1] - reduced_cost1
        if reversed_changed_cost1 < changed_cost1:
            selected_task2 = (v2, u2)
            changed_cost1 = reversed_changed_cost1

        new_solution.costs[selected_arc_index1] += changed_cost1
        new_solution.total_cost += changed_cost1
        new_solution.loads[selected_arc_index1] += task2.demand - task1.demand

        selected_arc1.insert(selected_task_index1, selected_task2)

        # second arc cost change : insert task1 into arc2
        reduced_cost2 = self.min_dist[pre_end2, u2] + task2.cost + self.min_dist[v2, next_start2]
        changed_cost2 = self.min_dist[pre_end2, u1] + task1.cost + self.min_dist[v1, next_start2] - reduced_cost2
        reversed_changed_cost2 = self.min_dist[pre_end2, v1] + task1.cost + self.min_dist[u1, next_start2] - reduced_cost2
        if reversed_changed_cost2 < changed_cost2:
            selected_task1 = (v1, u1)
            changed_cost2 = reversed_changed_cost2

        new_solution.costs[selected_arc_index2] += changed_cost2
        new_solution.total_cost += changed_cost2
        new_solution.loads[selected_arc_index2] += task1.demand - task2.demand

        selected_arc2.insert(selected_task_index2, selected_task1)

        if selected_arc_index1 == selected_arc_index2:
            new_solution.total_cost = get_cost(new_solution, self.info)

        new_solution.check_valid()

        return new_solution

    def get_total_cost(self, x):
        return x.total_cost

    def local_search(self, solution: Solution):
        new_solution = None
        while not new_solution:
            new_solution = min([move(solution) for move in self.move], key=self.get_total_cost)
            discard_prop = 0 if new_solution.is_valid else 0.6
            if random.random() < discard_prop:
                new_solution = None

        return new_solution

    def step(self):
        for individual in self.population.copy():
            if random.random() > individual.discard_prop:
                if random.random() > self.mutation_rate:
                    new_solution = min([move(individual) for move in self.move], key=self.get_total_cost)
                    if random.random() > new_solution.discard_prop:
                        self.population.add(new_solution)
            else:
                self.population.remove(individual)

        while len(self.population) > self.population_size:
            worst_individual = max(self.population, key=self.get_total_cost)
            self.population.remove(worst_individual)

        valid_population = [p for p in self.population if p.is_valid]
        return min(valid_population, key=self.get_total_cost)

    @staticmethod
    def better(edge, selected_task, current_load, rule):
        return rule(edge, selected_task, current_load)
