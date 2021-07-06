from typing import List

from ee.clickhouse.queries.funnels.base import ClickhouseFunnelBase

MAX_INT_32 = 2147483647


class ClickhouseFunnelUnordered(ClickhouseFunnelBase):
    """
    Unordered Funnel is a funnel where the order of steps doesn't matter.

    ## Query Intuition

    Imagine a funnel with three events: A, B, and C.
    This query splits the problem into two parts:
    1. Given the first event is A, find the furthest everyone went starting from A.
       This finds any B's and C's that happen after A (without ordering them)
    2. Repeat the above, assuming first event to be B, and then C.
    
    Then, the outer query unions the result of (2) and takes the maximum of these.

    ## Results

    The result format is the same as the basic funnel, i.e. [step, count].
    Here, `step_i` (0 indexed) signifies the number of people that did at least `i+1` steps.
    """

    def get_query(self, format_properties):

        max_steps = len(self._filter.entities)

        return f"""
        SELECT {self._get_count_columns(max_steps)} {self._get_step_time_avgs(max_steps)} FROM (
            {self.get_step_counts_query()}
        ) SETTINGS allow_experimental_window_functions = 1
        """

    def get_step_counts_query(self):

        max_steps = len(self._filter.entities)
        union_queries = []
        entities_to_use = list(self._filter.entities)

        partition_select = self.get_partition_cols(1, max_steps)
        sorting_condition = self.get_sorting_condition(max_steps)

        for i in range(max_steps):
            inner_query = f"""
                SELECT 
                person_id,
                timestamp,
                {partition_select}
                FROM ({self._get_inner_event_query(entities_to_use, f"events_{i}")})
            """

            formatted_query = f"""
                SELECT *, {sorting_condition} AS steps_initial {self._get_step_times(max_steps)} FROM (
                        {inner_query}
                    ) WHERE step_0 = 1"""

            #  rotate entities by 1 to get new first event
            entities_to_use.append(entities_to_use.pop(0))
            union_queries.append(formatted_query)

        union_formatted_query = " UNION ALL ".join(union_queries)

        return f"""
        SELECT person_id, max(steps_initial) AS steps {self._get_step_time_avgs(max_steps)} FROM (
                {union_formatted_query}
        ) GROUP BY person_id
        """

    def _get_step_times(self, max_steps: int):
        def get_basic_step_time(current_index: int, max_steps: int):
            elements = []
            for i in range(max_steps):
                if i == current_index:
                    continue

                conversion_time = f"if(toDateTime(latest_{i}) < toDateTime(latest_{current_index}), dateDiff('second', assumeNotNull(latest_{i}), assumeNotNull(latest_{current_index})), {MAX_INT_32})"
                elements.append(conversion_time)
            return f"arrayMin([{','.join(elements)}])"

        conditions: List[str] = []
        for i in range(1, max_steps):
            conditions.append(
                f"if(isNotNull(latest_{i}), {get_basic_step_time(i, max_steps)}, NULL) step_{i}_average_conversion_time"
            )

        formatted = ", ".join(conditions)
        return f", {formatted}" if formatted else ""

    def get_sorting_condition(self, max_steps: int):

        basic_conditions: List[str] = []
        for i in range(1, max_steps):
            basic_conditions.append(
                f"if(latest_0 < latest_{i} AND latest_{i} <= latest_0 + INTERVAL {self._filter.funnel_window_days} DAY, 1, 0)"
            )

        return f"arraySum([{','.join(basic_conditions)}, 1])"

    # TODO: copied from funnel.py. Once the new funnel query replaces old one, the base format_results function can use this
    def _format_results(self, results):
        # Format of this is [step order, person count (that reached that step), array of person uuids]
        steps = []
        total_people = 0

        for step in reversed(self._filter.entities):

            if results[0] and len(results[0]) > 0:
                total_people += results[0][step.order]

            serialized_result = self._serialize_step(step, total_people, [])
            if step.order > 0:
                serialized_result.update(
                    {"average_conversion_time": results[0][step.order + len(self._filter.entities) - 1]}
                )
            else:
                serialized_result.update({"average_conversion_time": None})
            steps.append(serialized_result)

        return steps[::-1]  #  reverse
