from typing import Optional

from posthog.models.filters.filter import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.queries.actor_base_query import ActorBaseQuery
from posthog.queries.funnels.funnel_unordered import ClickhouseFunnelUnordered
from posthog.queries.funnels.sql import FUNNEL_PERSONS_BY_STEP_SQL


class ClickhouseFunnelUnorderedActors(ClickhouseFunnelUnordered, ActorBaseQuery):
    _filter: Filter
    QUERY_TYPE = "funnel_unordered_actors"

    @cached_property
    def aggregation_group_type_index(self):
        return self._filter.aggregation_group_type_index

    def _get_funnel_person_step_events(self):
        # Unordered funnels does not support matching events (and thereby recordings),
        # but it simplifies the logic if we return an empty array for matching events
        if self._filter.include_recordings:
            return ", array() as matching_events"
        return ""

    def actor_query(
        self,
        limit_actors: Optional[bool] = True,
        extra_fields: Optional[list[str]] = None,
    ):
        extra_fields_string = ", ".join([self._get_timestamp_outer_select()] + (extra_fields or []))
        return (
            FUNNEL_PERSONS_BY_STEP_SQL.format(
                steps_per_person_query=self.get_step_counts_query(),
                persons_steps=self._get_funnel_person_step_condition(),
                matching_events_select_statement=self._get_funnel_person_step_events(),
                extra_fields=extra_fields_string,
                limit="LIMIT %(limit)s" if limit_actors else "",
                offset="OFFSET %(offset)s" if limit_actors else "",
            ),
            self.params,
        )
