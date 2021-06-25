from typing import List

from ee.clickhouse.queries.funnels.base import ClickhouseFunnelBase


class ClickhouseFunnelUnordered(ClickhouseFunnelBase):
    def get_query(self, format_properties):
        return self.get_step_counts_query()

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
                SELECT *, {sorting_condition} AS steps FROM (
                        {inner_query}
                    ) WHERE step_0 = 1"""

            #  rotate entities by 1 to get new first event
            entities_to_use.append(entities_to_use.pop(0))
            union_queries.append(formatted_query)

        union_formatted_query = " UNION ALL ".join(union_queries)

        return f"""
        SELECT furthest, count(1), groupArray(100)(person_id) FROM (
            SELECT person_id, max(steps) AS furthest FROM (
                {union_formatted_query}
            ) GROUP BY person_id
        ) GROUP BY furthest SETTINGS allow_experimental_window_functions = 1
        """

    def get_sorting_condition(self, max_steps: int):

        basic_conditions: List[str] = []
        for i in range(1, max_steps):
            basic_conditions.append(
                f"if(latest_0 < latest_{i} AND latest_{i} <= latest_0 + INTERVAL {self._filter.funnel_window_days} DAY, 1, 0)"
            )

        return f"arraySum([{','.join(basic_conditions)}, 1])"
