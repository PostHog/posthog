from typing import List

from ee.clickhouse.queries.funnels.base import ClickhouseFunnelBase


class ClickhouseFunnel(ClickhouseFunnelBase):
    def get_query(self, format_properties):

        steps_per_person_query = self.get_step_counts_query()
        max_steps = len(self._filter.entities)

        breakdown_clause = self._get_breakdown_prop()

        return f"""
        SELECT {self._get_count_columns(max_steps)} {self._get_step_time_avgs(max_steps)} {breakdown_clause} FROM (
                {steps_per_person_query}
        ) {'GROUP BY prop' if breakdown_clause != '' else ''} SETTINGS allow_experimental_window_functions = 1
        """

    def get_step_counts_query(self):
        steps_per_person_query = self._get_steps_per_person_query()
        max_steps = len(self._filter.entities)
        breakdown_clause = self._get_breakdown_prop()

        return f"""SELECT person_id, max(steps) AS steps {self._get_step_time_avgs(max_steps)} {breakdown_clause} FROM (
            {steps_per_person_query}
        ) GROUP BY person_id {breakdown_clause}
        """

    def _format_results(self, results):
        if not results or len(results) == 0:
            return []

        if self._filter.breakdown:
            return [self._format_single_funnel(res, with_breakdown=True) for res in results]
        else:
            return self._format_single_funnel(results[0])

    def _format_single_funnel(self, result, with_breakdown=False):
        # Format of this is [step order, person count (that reached that step), array of person uuids]
        steps = []
        total_people = 0

        for step in reversed(self._filter.entities):

            if result and len(result) > 0:
                total_people += result[step.order]

            serialized_result = self._serialize_step(step, total_people, [])
            if step.order > 0:
                serialized_result.update(
                    {"average_conversion_time": result[step.order + len(self._filter.entities) - 1]}
                )
            else:
                serialized_result.update({"average_conversion_time": None})

            if with_breakdown:
                serialized_result.update({"breakdown": result[-1][1:-1]})  # strip quotes

            steps.append(serialized_result)

        return steps[::-1]  #  reverse
