import uuid
from typing import Any, Optional, cast

from rest_framework.exceptions import ValidationError

from posthog.models.entity.entity import Entity
from posthog.queries.funnels.base import ClickhouseFunnelBase
from posthog.queries.util import correct_result_for_sampling


class ClickhouseFunnelUnordered(ClickhouseFunnelBase):
    """
    Unordered Funnel is a funnel where the order of steps doesn't matter.

    ## Query Intuition

    Imagine a funnel with three events: A, B, and C.
    This query splits the problem into two parts:
    1. Given the first event is A, find the furthest everyone went starting from A.
       This finds any B's and C's that happen after A (without ordering them)
    2. Repeat the above, assuming first event to be B, and then C.

    Then, the outer query unions the result of (2) and takes the maximum of these.

    ## Results

    The result format is the same as the basic funnel, i.e. [step, count].
    Here, `step_i` (0 indexed) signifies the number of people that did at least `i+1` steps.

    ## Exclusion Semantics
    For unordered funnels, exclusion is a bit weird. It means, given all ordering of the steps,
    how far can you go without seeing an exclusion event.
    If you see an exclusion event => you're discarded.
    See test_advanced_funnel_multiple_exclusions_between_steps for details.
    """

    QUERY_TYPE = "funnel_unordered"

    def _serialize_step(
        self,
        step: Entity,
        count: int,
        people: Optional[list[uuid.UUID]] = None,
        sampling_factor: Optional[float] = None,
    ) -> dict[str, Any]:
        return {
            "action_id": None,
            "name": f"Completed {step.index+1} step{'s' if step.index != 0 else ''}",
            "custom_name": None,
            "order": step.index,
            "people": people if people else [],
            "count": correct_result_for_sampling(count, sampling_factor),
            "type": step.type,
        }

    def get_query(self):
        max_steps = len(self._filter.entities)

        for exclusion in self._filter.exclusions:
            if exclusion.funnel_from_step != 0 or exclusion.funnel_to_step != max_steps - 1:
                raise ValidationError("Partial Exclusions not allowed in unordered funnels")

        breakdown_clause = self._get_breakdown_prop()

        return f"""
        SELECT {self._get_count_columns(max_steps)} {self._get_step_time_avgs(max_steps)} {self._get_step_time_median(max_steps)} {breakdown_clause} FROM (
            {self.get_step_counts_query()}
        ) {'GROUP BY prop' if breakdown_clause != '' else ''}
        {self._order_by(max_steps) if breakdown_clause != '' else ''}
        {self._get_limit() if breakdown_clause != '' else ''}
        """

    def get_step_counts_query(self):
        max_steps = len(self._filter.entities)

        union_query = self.get_step_counts_without_aggregation_query()
        breakdown_clause = self._get_breakdown_prop()
        inner_timestamps, outer_timestamps = self._get_timestamp_selects()

        return f"""
            SELECT aggregation_target, steps {self._get_step_time_avgs(max_steps, inner_query=True)} {self._get_step_time_median(max_steps, inner_query=True)} {breakdown_clause} {outer_timestamps} {self._get_person_and_group_properties(aggregate=True)} FROM (
                SELECT aggregation_target, steps, max(steps) over (PARTITION BY aggregation_target {breakdown_clause}) as max_steps {self._get_step_time_names(max_steps)} {breakdown_clause} {inner_timestamps} {self._get_person_and_group_properties()} FROM (
                        {union_query}
                )
            ) GROUP BY aggregation_target, steps {breakdown_clause}
            HAVING steps = max(max_steps)
        """

    def get_step_counts_without_aggregation_query(self):
        max_steps = len(self._filter.entities)
        union_queries = []
        entities_to_use = list(self._filter.entities)

        partition_select = self._get_partition_cols(1, max_steps)
        sorting_condition = self.get_sorting_condition(max_steps)
        breakdown_clause = self._get_breakdown_prop(group_remaining=True)
        exclusion_clause = self._get_exclusion_condition()

        for i in range(max_steps):
            inner_query = f"""
                SELECT
                aggregation_target,
                timestamp,
                {partition_select}
                {breakdown_clause}
                {self._get_person_and_group_properties()}
                FROM ({self._get_inner_event_query(entities_to_use, f"events_{i}")})
            """

            formatted_query = f"""
                SELECT *, {sorting_condition} AS steps {exclusion_clause} {self._get_step_times(max_steps)} {self._get_person_and_group_properties()} FROM (
                        {inner_query}
                    ) WHERE step_0 = 1
                    {'AND exclusion = 0' if exclusion_clause else ''}
                    """

            #  rotate entities by 1 to get new first event
            entities_to_use.append(entities_to_use.pop(0))
            union_queries.append(formatted_query)

        return " UNION ALL ".join(union_queries)

    def _get_step_times(self, max_steps: int):
        conditions: list[str] = []

        conversion_times_elements = []
        for i in range(max_steps):
            conversion_times_elements.append(f"latest_{i}")

        conditions.append(f"arraySort([{','.join(conversion_times_elements)}]) as conversion_times")

        for i in range(1, max_steps):
            conditions.append(
                f"if(isNotNull(conversion_times[{i+1}]) AND conversion_times[{i+1}] <= conversion_times[{i}] + INTERVAL {self._filter.funnel_window_interval} {self._filter.funnel_window_interval_unit_ch()}, "
                f"dateDiff('second', conversion_times[{i}], conversion_times[{i+1}]), NULL) step_{i}_conversion_time"
            )
            # array indices in ClickHouse are 1-based :shrug:

        formatted = ", ".join(conditions)
        return f", {formatted}" if formatted else ""

    def get_sorting_condition(self, max_steps: int):
        conditions = []

        event_times_elements = []
        for i in range(max_steps):
            event_times_elements.append(f"latest_{i}")

        conditions.append(f"arraySort([{','.join(event_times_elements)}]) as event_times")
        # replacement of latest_i for whatever query part requires it, just like conversion_times
        basic_conditions: list[str] = []
        for i in range(1, max_steps):
            basic_conditions.append(
                f"if(latest_0 < latest_{i} AND latest_{i} <= latest_0 + INTERVAL {self._filter.funnel_window_interval} {self._filter.funnel_window_interval_unit_ch()}, 1, 0)"
            )

        conditions.append(f"arraySum([{','.join(basic_conditions)}, 1])")

        if basic_conditions:
            return ",".join(conditions)
        else:
            return "1"

    def _get_exclusion_condition(self):
        if not self._filter.exclusions:
            return ""

        conditions = []
        for exclusion_id, exclusion in enumerate(self._filter.exclusions):
            from_time = f"latest_{exclusion.funnel_from_step}"
            to_time = f"event_times[{cast(int, exclusion.funnel_to_step) + 1}]"
            exclusion_time = f"exclusion_{exclusion_id}_latest_{exclusion.funnel_from_step}"
            condition = (
                f"if( {exclusion_time} > {from_time} AND {exclusion_time} < "
                f"if(isNull({to_time}), {from_time} + INTERVAL {self._filter.funnel_window_interval} {self._filter.funnel_window_interval_unit_ch()}, {to_time}), 1, 0)"
            )
            conditions.append(condition)

        if conditions:
            return f", arraySum([{','.join(conditions)}]) as exclusion"
        else:
            return ""
