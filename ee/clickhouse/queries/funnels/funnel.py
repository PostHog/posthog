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
        max_steps = len(self._filter.entities)

        return f"""
        SELECT {self._get_count_columns(max_steps)} {self._get_step_time_avgs(max_steps)} FROM (
            SELECT person_id, max(steps) AS furthest {self._get_step_time_avgs(max_steps)} FROM (
                {steps_per_person_query}
            ) GROUP BY person_id
        ) SETTINGS allow_experimental_window_functions = 1
        """

    def _get_count_columns(self, max_steps: int):
        cols: List[str] = []

        for i in range(max_steps):
            cols.append(f"countIf(furthest = {i + 1}) step_{i + 1}")

        return ", ".join(cols)

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

    # TODO: include in the inner query to handle breakdown
    def _get_breakdown_prop(self) -> str:
        if self._filter.breakdown:
            return ", prop"
        else:
            return ""

    # TODO: include in the inner query to handle time to convert
    def _get_step_time_avgs(self, max_steps: int):
        conditions: List[str] = []
        for i in range(1, max_steps):
            conditions.append(f"avg(step_{i}_average_conversion_time) step_{i}_average_conversion_time")

        formatted = ", ".join(conditions)
        return f", {formatted}" if formatted else ""
