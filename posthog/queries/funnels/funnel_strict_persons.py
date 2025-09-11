from typing import Optional

from posthog.models.filters.filter import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.queries.actor_base_query import ActorBaseQuery
from posthog.queries.funnels.funnel_strict import ClickhouseFunnelStrict
from posthog.queries.funnels.sql import FUNNEL_PERSONS_BY_STEP_SQL


class ClickhouseFunnelStrictActors(ClickhouseFunnelStrict, ActorBaseQuery):
    _filter: Filter
    QUERY_TYPE = "funnel_strict_actors"

    @cached_property
    def aggregation_group_type_index(self):
        return self._filter.aggregation_group_type_index

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
