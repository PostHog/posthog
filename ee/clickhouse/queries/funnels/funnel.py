from typing import List, Tuple, cast

from ee.clickhouse.queries.breakdown_props import get_breakdown_cohort_name
from ee.clickhouse.queries.funnels.base import ClickhouseFunnelBase
from posthog.models.cohort import Cohort


class ClickhouseFunnel(ClickhouseFunnelBase):
    """
    A basic ordered funnel.

    ## Query Intuition
    We start with all events of interest (coming from the `FunnelEventQuery`). The query runs in different levels: at each
    level, we first get the minimum timestamp of every event following the previous event. Then, we trickle up the levels, till we get to the top level,
    which implies all events are sorted in increasing order.
    Each level is a subquery.

    ## Exclusion Intuition
    Event exclusion between steps means that if this specific event happened between two funnel steps, we disqualify the user, not showing them in the results.
    To include event exclusions inside the funnel, the critical insight is that the exclusion is just like a parallel step to the funnel step that happens after
    the exclusion start step.
    For example, if we have a funnel with steps [1, 2, 3, 4] and we want to exclude events between step 2 and step 4, then the exclusion step semantics are just
    like step 3 semantics. We want to find this event after step 2.
    Since it's a parallel step, we don't need to add an extra level, we can reuse the existing levels.
    See `get_comparison_cols` and `_get_partition_cols` for how this works.

    Exclusion doesn't support duplicates like: steps [event 1, event 2], and excluding event 1 between steps 1 and 2.

    """

    def get_query(self):
        max_steps = len(self._filter.entities)

        breakdown_clause = self._get_breakdown_prop()

        return f"""
        SELECT {self._get_count_columns(max_steps)} {self._get_people_columns(max_steps)} {self._get_step_time_avgs(max_steps)} {self._get_step_time_median(max_steps)} {breakdown_clause} FROM (
                {self.get_step_counts_query()}
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
        inner_timestamps, outer_timestamps = self._get_timestamp_selects()

        return f"""
            SELECT person_id, steps {self._get_step_time_avgs(max_steps, inner_query=True)} {self._get_step_time_median(max_steps, inner_query=True)} {breakdown_clause} {outer_timestamps} FROM (
                SELECT person_id, steps, max(steps) over (PARTITION BY person_id {breakdown_clause}) as max_steps {self._get_step_time_names(max_steps)} {breakdown_clause} {inner_timestamps} FROM (
                        {steps_per_person_query}
                )
            ) GROUP BY person_id, steps {breakdown_clause}
            HAVING steps = max_steps
            SETTINGS allow_experimental_window_functions = 1
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
                relevant_people += result[cast(int, step.order) + num_entities]

            serialized_result = self._serialize_step(step, total_people, relevant_people[0:100])
            if cast(int, step.order) > 0:
                serialized_result.update(
                    {
                        "average_conversion_time": result[cast(int, step.order) + num_entities * 2 - 1],
                        "median_conversion_time": result[cast(int, step.order) + num_entities * 3 - 2],
                    }
                )
            else:
                serialized_result.update({"average_conversion_time": None, "median_conversion_time": None})

            if with_breakdown:
                # breakdown will return a display ready value
                # breakdown_value will return the underlying id if different from display ready value (ex: cohort id)
                serialized_result.update(
                    {
                        "breakdown": get_breakdown_cohort_name(result[-1])
                        if self._filter.breakdown_type == "cohort"
                        else result[-1],
                        "breakdown_value": result[-1],
                    }
                )
                # important to not try and modify this value any how - as these are keys for fetching persons

            steps.append(serialized_result)

        return steps[::-1]  #  reverse

    def get_step_counts_without_aggregation_query(self):
        formatted_query = ""
        max_steps = len(self._filter.entities)
        if max_steps >= 2:
            formatted_query = self.build_step_subquery(2, max_steps)
            breakdown_query = self._get_breakdown_prop()
        else:
            formatted_query = self._get_inner_event_query()
            breakdown_query = self._get_breakdown_prop(group_remaining=True)

        exclusion_clause = self._get_exclusion_condition()

        return f"""
        SELECT *, {self._get_sorting_condition(max_steps, max_steps)} AS steps {exclusion_clause} {self._get_step_times(max_steps)} {breakdown_query} FROM (
            {formatted_query}
        ) WHERE step_0 = 1
        {'AND exclusion = 0' if exclusion_clause else ''}
        SETTINGS allow_experimental_window_functions = 1
        """

    def _get_comparison_at_step(self, index: int, level_index: int):
        or_statements: List[str] = []

        for i in range(level_index, index + 1):
            or_statements.append(f"latest_{i} < latest_{level_index - 1}")

        return " OR ".join(or_statements)

    def get_comparison_cols(self, level_index: int, max_steps: int):
        """
        level_index: The current smallest comparison step. Everything before
        level index is already at the minimum ordered timestamps.
        """
        cols: List[str] = []
        for i in range(0, max_steps):
            cols.append(f"step_{i}")
            if i < level_index:
                cols.append(f"latest_{i}")
                for exclusion_id, exclusion in enumerate(self._filter.exclusions):
                    if cast(int, exclusion.funnel_from_step) + 1 == i:
                        cols.append(f"exclusion_{exclusion_id}_latest_{exclusion.funnel_from_step}")
            else:
                comparison = self._get_comparison_at_step(i, level_index)
                cols.append(f"if({comparison}, NULL, latest_{i}) as latest_{i}")

                for exclusion_id, exclusion in enumerate(self._filter.exclusions):
                    if cast(int, exclusion.funnel_from_step) + 1 == i:
                        exclusion_identifier = f"exclusion_{exclusion_id}_latest_{exclusion.funnel_from_step}"
                        cols.append(
                            f"if({exclusion_identifier} < latest_{exclusion.funnel_from_step}, NULL, {exclusion_identifier}) as {exclusion_identifier}"
                        )

        return ", ".join(cols)

    def build_step_subquery(self, level_index: int, max_steps: int):
        if level_index >= max_steps:
            return f"""
            SELECT
            person_id,
            timestamp,
            {self._get_partition_cols(1, max_steps)}
            {self._get_breakdown_prop(group_remaining=True)}
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
