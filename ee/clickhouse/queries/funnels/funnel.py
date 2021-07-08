from typing import List

from ee.clickhouse.queries.funnels.base import ClickhouseFunnelBase


class ClickhouseFunnel(ClickhouseFunnelBase):
    def get_query(self, format_properties):

        steps_per_person_query = self.get_step_counts_query()
        max_steps = len(self._filter.entities)

        breakdown_clause = self._get_breakdown_prop()

        return f"""
        SELECT {self._get_count_columns(max_steps)} {self._get_people_columns(max_steps)} {self._get_step_time_avgs(max_steps)} {breakdown_clause} FROM (
                {steps_per_person_query}
        ) {'GROUP BY prop' if breakdown_clause != '' else ''} SETTINGS allow_experimental_window_functions = 1
        """

    def _get_people_columns(self, max_steps: int):
        cols: List[str] = []

        for i in range(max_steps):
            cols.append(f"groupArrayIf(100)(DISTINCT person_id, steps = {i + 1}) step_people_{i + 1}")

        formatted = ", ".join(cols)
        return f", {formatted}" if formatted else ""

    def get_step_counts_query(self):
        steps_per_person_query = self.get_step_counts_without_aggregation_query()
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
        relevant_people = []
        total_people = 0

        num_entities = len(self._filter.entities)

        for step in reversed(self._filter.entities):

            if result and len(result) > 0:
                total_people += result[step.order]
                relevant_people += result[step.order + num_entities]

            serialized_result = self._serialize_step(step, total_people, relevant_people[0:100])
            if step.order > 0:
                serialized_result.update({"average_conversion_time": result[step.order + num_entities * 2 - 1]})
            else:
                serialized_result.update({"average_conversion_time": None})

            if with_breakdown:
                serialized_result.update({"breakdown": result[-1][1:-1]})  # strip quotes

            steps.append(serialized_result)

        return steps[::-1]  #  reverse

    def get_step_counts_without_aggregation_query(self):
        formatted_query = ""
        max_steps = len(self._filter.entities)
        if max_steps >= 2:
            formatted_query = self.build_step_subquery(2, max_steps)
        else:
            formatted_query = self._get_inner_event_query()

        return f"""
        SELECT *, {self._get_sorting_condition(max_steps, max_steps)} AS steps {self._get_step_times(max_steps)} {self._get_breakdown_prop()} FROM (
            {formatted_query}
        ) WHERE step_0 = 1
        """

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

    def build_step_subquery(self, level_index: int, max_steps: int):
        if level_index >= max_steps:
            return f"""
            SELECT 
            person_id,
            timestamp,
            {self._get_partition_cols(1, max_steps)}
            {self._get_breakdown_prop()}
            FROM ({self._get_inner_event_query()})
            """
        else:
            return f"""
            SELECT 
            person_id,
            timestamp,
            {self._get_partition_cols(level_index, max_steps)}
            {self._get_breakdown_prop()}
            FROM (
                SELECT 
                person_id,
                timestamp,
                {self.get_comparison_cols(level_index, max_steps)}
                {self._get_breakdown_prop()}
                FROM ({self.build_step_subquery(level_index + 1, max_steps)})
            )
            """
