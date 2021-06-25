from itertools import combinations
from typing import List

from ee.clickhouse.queries.funnels.base import ClickhouseFunnelBase
from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnelNew
from posthog.models import Person


class ClickhouseFunnelUnordered(ClickhouseFunnelNew):
    def get_query(self, format_properties):
        return self.get_step_counts_query()

    def get_step_counts_query(self):

        max_steps = len(self._filter.entities)
        union_queries = []
        entities_to_use = list(self._filter.entities)

        breakdown_prop = self._get_breakdown_prop()
        partition_select = self.get_partition_cols(1, max_steps)
        sorting_condition = self._get_sorting_condition(max_steps)

        for i in range(max_steps):
            inner_query = f"""
                SELECT 
                person_id,
                timestamp,
                {partition_select}
                {breakdown_prop}
                FROM ({self._get_inner_event_query(entities_to_use, f"events_{i}")})
            """

            formatted_query = f"""
                SELECT *, {sorting_condition} AS steps FROM (
                        {inner_query}
                    ) WHERE step_0 = 1"""

            #  rotate entities by 1 to get new first event
            entities_to_use.append(entities_to_use.pop(0))
            union_queries.append(formatted_query)

        union_formatted_query = " UNION ALL ".join(union_queries)

        return f"""
        SELECT furthest, count(1), groupArray(100)(person_id) {breakdown_prop} FROM (
            SELECT person_id, max(steps) AS furthest {breakdown_prop} FROM (
                {union_formatted_query}
            ) GROUP BY person_id {breakdown_prop}
        ) GROUP BY furthest {breakdown_prop} SETTINGS allow_experimental_window_functions = 1
        """

    def _format_results(self, results):
        # Format of this is [step order, person count (that reached that step), array of person uuids]

        steps = []
        relevant_people = []
        total_people = 0

        for step in reversed(self._filter.entities):
            # Clickhouse step order starts at one, hence the +1
            result_step = [x for x in results if step.order + 1 == x[0]]
            if len(result_step) > 0:
                total_people += result_step[0][1]
                relevant_people += result_step[0][2]
            steps.append(self._serialize_step(step, total_people, relevant_people[0:100]))

        return steps[::-1]  #  reverse

    def _get_sorting_condition(self, max_steps: int):
        def sorting_condition_helper(current_index: int):
            if current_index == 1:
                return "1"

            condition_combinations = [
                f"({' AND '.join(combination)})" for combination in combinations(basic_conditions, current_index - 1)
            ]
            return f"if({' OR '.join(condition_combinations)}, {current_index}, {sorting_condition_helper(current_index - 1)})"

        basic_conditions: List[str] = []
        for i in range(1, max_steps):
            basic_conditions.append(
                f"latest_0 < latest_{i} AND latest_{i} <= latest_0 + INTERVAL {self._filter.funnel_window_days} DAY"
            )

        return sorting_condition_helper(max_steps)
