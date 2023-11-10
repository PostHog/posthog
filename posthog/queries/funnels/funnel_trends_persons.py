from typing import Optional

from rest_framework.exceptions import ValidationError

from posthog.constants import DROP_OFF, ENTRANCE_PERIOD_START
from posthog.models.filters.filter import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.queries.actor_base_query import ActorBaseQuery
from posthog.queries.funnels.funnel_trends import ClickhouseFunnelTrends
from posthog.queries.funnels.sql import FUNNEL_PERSONS_BY_STEP_SQL


class ClickhouseFunnelTrendsActors(ClickhouseFunnelTrends, ActorBaseQuery):
    _filter: Filter
    QUERY_TYPE = "funnel_trends_actors"

    @cached_property
    def aggregation_group_type_index(self):
        return self._filter.aggregation_group_type_index

    def _get_funnel_person_step_events(self):
        if self._filter.include_recordings:
            # Get the event that should be used to match the recording
            funnel_to_step = self._filter.funnel_to_step
            is_drop_off = self._filter.drop_off

            if funnel_to_step is None or is_drop_off:
                # If there is no funnel_to_step or if we are looking for drop off, we need to get the users final event
                return ", final_matching_events as matching_events"
            else:
                # Otherwise, we return the event of the funnel_to_step
                self.params.update({"matching_events_step_num": funnel_to_step})
                return ", step_%(matching_events_step_num)s_matching_events as matching_events"
        return ""

    def actor_query(self, limit_actors: Optional[bool] = True):
        drop_off = self._filter.drop_off
        if drop_off is None:
            raise ValidationError(f"Filter parameter {DROP_OFF} must be provided and a bool for funnel trends persons!")

        entrance_period_start = self._filter.entrance_period_start
        if not entrance_period_start:
            raise ValidationError(
                f"Filter parameter {ENTRANCE_PERIOD_START} must be provided and a datetime for funnel trends persons!"
            )

        step_counts_query = self.get_step_counts_without_aggregation_query(
            specific_entrance_period_start=entrance_period_start
        )
        # Expects multiple rows for same person, first event time, steps taken.
        self.params.update(self.funnel_order.params)

        (
            _,
            reached_to_step_count_condition,
            did_not_reach_to_step_count_condition,
        ) = self.get_steps_reached_conditions()

        return (
            FUNNEL_PERSONS_BY_STEP_SQL.format(
                steps_per_person_query=step_counts_query,
                persons_steps=did_not_reach_to_step_count_condition if drop_off else reached_to_step_count_condition,
                matching_events_select_statement=self._get_funnel_person_step_events(),
                extra_fields="",
                limit="LIMIT %(limit)s" if limit_actors else "",
                offset="OFFSET %(offset)s" if limit_actors else "",
            ),
            self.params,
        )
