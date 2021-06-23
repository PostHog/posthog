from typing import List

from ee.clickhouse.queries.funnels.base import ClickhouseFunnelBase
from ee.clickhouse.sql.funnels.funnel import FUNNEL_SQL


class ClickhouseFunnel(ClickhouseFunnelBase):
    def get_query(self, format_properties):
        return FUNNEL_SQL.format(**format_properties)


class ClickhouseFunnelNew(ClickhouseFunnelBase):
    def get_query(self, format_properties):
        return FUNNEL_SQL.format(**format_properties)

    def test_query(self):
        return self.get_step_counts_query()

    def get_step_counts_query(self):

        formatted_query = ""
        max_steps = len(self._filter.entities)
        if max_steps >= 2:
            formatted_query = self.build_step_subquery(2, max_steps)
        else:
            formatted_query = super()._get_inner_event_query()

        breakdown_prop = self._get_breakdown_prop()

        return f"""
        SELECT {self._get_count_columns(max_steps)}, {self._get_step_time_avgs(max_steps)} {breakdown_prop} FROM (
            SELECT person_id, {self._get_step_time_avgs(max_steps)}, max(steps) AS furthest {breakdown_prop} FROM (
                SELECT *, {self._get_sorting_condition(max_steps, max_steps)} AS steps, {self._get_step_times(max_steps)} FROM (
                    {formatted_query}
                ) WHERE step_0 = 1
            ) GROUP BY person_id {breakdown_prop}
        ) {'GROUP BY prop' if breakdown_prop != '' else ''} SETTINGS allow_experimental_window_functions = 1
        """

    def build_step_subquery(self, level_index: int, max_steps: int):
        breakdown_prop = self._get_breakdown_prop()
        if level_index >= max_steps:
            return f"""
            SELECT 
            person_id,
            timestamp,
            {self.get_partition_cols(1, max_steps)}
            {breakdown_prop}
            FROM ({super()._get_inner_event_query()})
            """
        else:
            return f"""
            SELECT 
            person_id,
            timestamp,
            {self.get_partition_cols(level_index, max_steps)}
            {breakdown_prop}
            FROM (
                SELECT 
                person_id,
                timestamp,
                {self.get_comparison_cols(level_index, max_steps)}
                {breakdown_prop}
                FROM ({self.build_step_subquery(level_index + 1, max_steps)})
            )
            """

    def get_partition_cols(self, level_index: int, max_steps: int):
        cols: List[str] = []
        for i in range(0, max_steps):
            cols.append(f"step_{i}")
            if i < level_index:
                cols.append(f"latest_{i}")
            else:
                cols.append(
                    f"min(latest_{i}) over (PARTITION by person_id ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) latest_{i}"
                )
        return ", ".join(cols)

    def get_comparison_cols(self, level_index: int, max_steps: int):
        cols: List[str] = []
        for i in range(0, max_steps):
            cols.append(f"step_{i}")
            if i < level_index:
                cols.append(f"latest_{i}")
            else:
                comparison = self._get_comparison_at_step(i, level_index)
                cols.append(f"if({comparison}, NULL, latest_{i}) as latest_{i}")
        return ", ".join(cols)

    def _get_breakdown_prop(self) -> str:
        if self._filter.breakdown:
            return ", prop"
        else:
            return ""

    def _get_comparison_at_step(self, index: int, level_index: int):
        or_statements: List[str] = []

        for i in range(level_index, index + 1):
            or_statements.append(f"latest_{i} < latest_{level_index - 1}")

        return " OR ".join(or_statements)

    def _get_sorting_condition(self, curr_index: int, max_steps: int):

        if curr_index == 1:
            return "0"

        conditions: List[str] = []
        for i in range(1, curr_index):
            conditions.append(f"latest_{i - 1} <= latest_{i }")
            conditions.append(f"latest_{i} <= latest_0 + INTERVAL {self._filter.funnel_window_days} DAY")

        return f"if({' AND '.join(conditions)}, {curr_index - 1}, {self._get_sorting_condition(curr_index - 1, max_steps)})"

    def _get_step_times(self, max_steps: int):
        conditions: List[str] = []
        for i in range(1, max_steps):
            conditions.append(
                f"if(isNotNull(latest_{i}), dateDiff('second', toDateTime(latest_{i - 1}), toDateTime(latest_{i})), NULL) step{i-1}ToStep{i}Time"
            )

        return ", ".join(conditions)

    def _get_step_time_avgs(self, max_steps: int):
        conditions: List[str] = []
        for i in range(1, max_steps):
            conditions.append(f"avg(step{i-1}ToStep{i}Time) step{i-1}ToStep{i}Time")

        return ", ".join(conditions)

    def _get_count_columns(self, max_steps: int):
        cols: List[str] = []

        for i in range(max_steps):
            cols.append(f"countIf(furthest = {i}) step_{i}")

        return ", ".join(cols)
