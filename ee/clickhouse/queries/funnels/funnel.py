from typing import List

from ee.clickhouse.queries.funnels.base import ClickhouseFunnelBase
from ee.clickhouse.sql.funnels.funnel import FUNNEL_SQL


class ClickhouseFunnel(ClickhouseFunnelBase):
    def get_query(self, format_properties):
        return FUNNEL_SQL.format(**format_properties)


class ClickhouseFunnelNew(ClickhouseFunnelBase):
    def get_query(self, format_properties):
        return self.get_step_counts_query()

    def get_step_counts_query(self):

        steps_per_person_query = self._get_steps_per_person_query()

        return f"""
        SELECT furthest, count(*), groupArray(100)(person_id) FROM (
            SELECT person_id, max(steps) AS furthest FROM (
                {steps_per_person_query}
            ) GROUP BY person_id
        ) GROUP BY furthest SETTINGS allow_experimental_window_functions = 1
        """

    # TODO: include in the inner query to handle breakdown
    def _get_breakdown_prop(self) -> str:
        if self._filter.breakdown:
            return ", prop"
        else:
            return ""

    # TODO: include in the inner query to handle time to convert
    def _get_step_times(self, max_steps: int):
        conditions: List[str] = []
        for i in range(1, max_steps):
            conditions.append(
                f"if(isNotNull(latest_{i}), dateDiff('second', toDateTime(latest_{i - 1}), toDateTime(latest_{i})), NULL) step{i-1}ToStep{i}Time"
            )

        return ", ".join(conditions)

    # TODO: include in the inner query to handle time to convert
    def _get_step_time_avgs(self, max_steps: int):
        conditions: List[str] = []
        for i in range(1, max_steps):
            conditions.append(f"avg(step{i-1}ToStep{i}Time) step{i-1}ToStep{i}Time")

        return ", ".join(conditions)
