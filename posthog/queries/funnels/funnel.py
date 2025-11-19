from typing import cast

from posthog.queries.funnels.base import ClickhouseFunnelBase


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

    QUERY_TYPE = "funnel"

    def get_query(self):
        max_steps = len(self._filter.entities)

        breakdown_clause = self._get_breakdown_prop()
        return f"""
        SELECT {self._get_count_columns(max_steps)} {self._get_step_time_avgs(max_steps)} {self._get_step_time_median(max_steps)} {breakdown_clause} FROM (
                {self.get_step_counts_query()}
        ) {'GROUP BY prop' if breakdown_clause != '' else ''}
        {self._order_by(max_steps) if breakdown_clause != '' else ''}
        {self._get_limit() if breakdown_clause != '' else ''}
        """

    def get_step_counts_query(self):
        steps_per_person_query = self.get_step_counts_without_aggregation_query()
        max_steps = len(self._filter.entities)
        breakdown_clause = self._get_breakdown_prop()
        inner_timestamps, outer_timestamps = self._get_timestamp_selects()

        return f"""
            SELECT aggregation_target, steps {self._get_step_time_avgs(max_steps, inner_query=True)} {self._get_step_time_median(max_steps, inner_query=True)} {self._get_matching_event_arrays(max_steps)} {breakdown_clause} {outer_timestamps} {self._get_person_and_group_properties(aggregate=True)} FROM (
                SELECT aggregation_target, steps, max(steps) over (PARTITION BY aggregation_target {breakdown_clause}) as max_steps {self._get_step_time_names(max_steps)} {self._get_matching_events(max_steps)} {breakdown_clause} {inner_timestamps} {self._get_person_and_group_properties()} FROM (
                        {steps_per_person_query}
                )
            ) GROUP BY aggregation_target, steps {breakdown_clause}
            HAVING steps = max(max_steps)
        """

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
        SELECT *, {self._get_sorting_condition(max_steps, max_steps)} AS steps {exclusion_clause} {self._get_step_times(max_steps)}{self._get_matching_events(max_steps)} {breakdown_query} {self._get_person_and_group_properties()} FROM (
            {formatted_query}
        ) WHERE step_0 = 1
        {'AND exclusion = 0' if exclusion_clause else ''}
        """

    def _get_comparison_at_step(self, index: int, level_index: int):
        or_statements: list[str] = []

        for i in range(level_index, index + 1):
            or_statements.append(f"latest_{i} < latest_{level_index - 1}")

        return " OR ".join(or_statements)

    def get_comparison_cols(self, level_index: int, max_steps: int):
        """
        level_index: The current smallest comparison step. Everything before
        level index is already at the minimum ordered timestamps.
        """
        cols: list[str] = []
        for i in range(0, max_steps):
            cols.append(f"step_{i}")
            if i < level_index:
                cols.append(f"latest_{i}")
                for field in self.extra_event_fields_and_properties:
                    cols.append(f'"{field}_{i}"')
                for exclusion_id, exclusion in enumerate(self._filter.exclusions):
                    if cast(int, exclusion.funnel_from_step) + 1 == i:
                        cols.append(f"exclusion_{exclusion_id}_latest_{exclusion.funnel_from_step}")
            else:
                comparison = self._get_comparison_at_step(i, level_index)
                cols.append(f"if({comparison}, NULL, latest_{i}) as latest_{i}")
                for field in self.extra_event_fields_and_properties:
                    cols.append(f'if({comparison}, NULL, "{field}_{i}") as "{field}_{i}"')
                for exclusion_id, exclusion in enumerate(self._filter.exclusions):
                    if cast(int, exclusion.funnel_from_step) + 1 == i:
                        exclusion_identifier = f"exclusion_{exclusion_id}_latest_{exclusion.funnel_from_step}"
                        cols.append(
                            f"if({exclusion_identifier} < latest_{exclusion.funnel_from_step}, NULL, {exclusion_identifier}) as {exclusion_identifier}"
                        )

        return ", ".join(cols)

    def build_step_subquery(self, level_index: int, max_steps: int, event_names_alias: str = "events"):
        if level_index >= max_steps:
            return f"""
            SELECT
            aggregation_target,
            timestamp,
            {self._get_partition_cols(1, max_steps)}
            {self._get_breakdown_prop(group_remaining=True)}
            {self._get_person_and_group_properties()}
            FROM ({self._get_inner_event_query(entity_name=event_names_alias)})
            """
        else:
            return f"""
            SELECT
            aggregation_target,
            timestamp,
            {self._get_partition_cols(level_index, max_steps)}
            {self._get_breakdown_prop()}
            {self._get_person_and_group_properties()}
            FROM (
                SELECT
                aggregation_target,
                timestamp,
                {self.get_comparison_cols(level_index, max_steps)}
                {self._get_breakdown_prop()}
                {self._get_person_and_group_properties()}
                FROM ({self.build_step_subquery(level_index + 1, max_steps)})
            )
            """
