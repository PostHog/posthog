from typing import List

from ee.clickhouse.queries.funnels.base import ClickhouseFunnelBase


class ClickhouseFunnelStrict(ClickhouseFunnelBase):
    def get_query(self):
        max_steps = len(self._filter.entities)
        return f"""
        SELECT {self._get_count_columns(max_steps)} {self._get_step_time_avgs(max_steps)} FROM (
            {self.get_step_counts_query()}
        ) SETTINGS allow_experimental_window_functions = 1
        """

    def get_step_counts_query(self):

        max_steps = len(self._filter.entities)

        formatted_query = self.get_step_counts_without_aggregation_query()

        return f"""
            SELECT person_id, max(steps) AS steps {self._get_step_time_avgs(max_steps)} FROM (
                {formatted_query}
            ) GROUP BY person_id
        """

    def get_step_counts_without_aggregation_query(self):
        max_steps = len(self._filter.entities)

        partition_select = self._get_partition_cols(1, max_steps)
        sorting_condition = self._get_sorting_condition(max_steps, max_steps)

        inner_query = f"""
            SELECT 
            person_id,
            timestamp,
            {partition_select}
            FROM ({self._get_inner_event_query(skip_entity_filter=True, skip_step_filter=True)})
        """

        formatted_query = f"""
            SELECT *, {sorting_condition} AS steps {self._get_step_times(max_steps)} FROM (
                    {inner_query}
                ) WHERE step_0 = 1"""

        return formatted_query

    def _get_partition_cols(self, level_index: int, max_steps: int):
        cols: List[str] = []
        for i in range(0, max_steps):
            cols.append(f"step_{i}")
            if i < level_index:
                cols.append(f"latest_{i}")
            else:
                cols.append(
                    f"min(latest_{i}) over (PARTITION by person_id ORDER BY timestamp DESC ROWS BETWEEN {i} PRECEDING AND {i} PRECEDING) latest_{i}"
                )
        return ", ".join(cols)
