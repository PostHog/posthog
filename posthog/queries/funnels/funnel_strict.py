from posthog.queries.funnels.base import ClickhouseFunnelBase


class ClickhouseFunnelStrict(ClickhouseFunnelBase):
    QUERY_TYPE = "funnel_strict"

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
            SELECT aggregation_target, steps {self._get_step_time_avgs(max_steps, inner_query=True)} {self._get_step_time_median(max_steps, inner_query=True)} {breakdown_clause} {outer_timestamps} {self._get_matching_event_arrays(max_steps)} {self._get_person_and_group_properties(aggregate=True)} FROM (
                SELECT aggregation_target, steps, max(steps) over (PARTITION BY aggregation_target {breakdown_clause}) as max_steps {self._get_step_time_names(max_steps)} {breakdown_clause} {inner_timestamps} {self._get_matching_events(max_steps)} {self._get_person_and_group_properties()} FROM (
                        {steps_per_person_query}
                )
            ) GROUP BY aggregation_target, steps {breakdown_clause}
            HAVING steps = max(max_steps)
        """

    def get_step_counts_without_aggregation_query(self):
        max_steps = len(self._filter.entities)

        partition_select = self._get_partition_cols(1, max_steps)
        sorting_condition = self._get_sorting_condition(max_steps, max_steps)
        breakdown_clause = self._get_breakdown_prop(group_remaining=True)

        inner_query = f"""
            SELECT
            aggregation_target,
            timestamp,
            {partition_select}
            {breakdown_clause}
            {self._get_person_and_group_properties()}
            FROM ({self._get_inner_event_query(skip_entity_filter=True, skip_step_filter=True)})
        """

        formatted_query = f"""
            SELECT *, {sorting_condition} AS steps {self._get_step_times(max_steps)}{self._get_matching_events(max_steps)} {self._get_person_and_group_properties()} FROM (
                    {inner_query}
                ) WHERE step_0 = 1"""

        return formatted_query

    def _get_partition_cols(self, level_index: int, max_steps: int):
        cols: list[str] = []
        for i in range(0, max_steps):
            cols.append(f"step_{i}")
            if i < level_index:
                cols.append(f"latest_{i}")
                for field in self.extra_event_fields_and_properties:
                    cols.append(f'"{field}_{i}"')
            else:
                cols.append(
                    f"min(latest_{i}) over (PARTITION by aggregation_target {self._get_breakdown_prop()} ORDER BY timestamp DESC ROWS BETWEEN {i} PRECEDING AND {i} PRECEDING) latest_{i}"
                )
                for field in self.extra_event_fields_and_properties:
                    cols.append(
                        f'min("{field}_{i}") over (PARTITION by aggregation_target {self._get_breakdown_prop()} ORDER BY timestamp DESC ROWS BETWEEN {i} PRECEDING AND {i} PRECEDING) "{field}_{i}"'
                    )
        return ", ".join(cols)
