from typing import List, Optional, cast

from ee.clickhouse.queries.actor_base_query import ActorBaseQuery
from ee.clickhouse.queries.funnels.funnel_strict import ClickhouseFunnelStrict
from ee.clickhouse.sql.funnels.funnel import FUNNEL_PERSONS_BY_STEP_SQL
from posthog.models.filters.filter import Filter
from posthog.models.filters.mixins.utils import cached_property


class ClickhouseFunnelStrictActors(ClickhouseFunnelStrict, ActorBaseQuery):
    _filter: Filter

    @cached_property
    def is_aggregating_by_groups(self) -> bool:
        return self._filter.aggregation_group_type_index is not None

    def actor_query(self, extra_fields: Optional[List[str]] = None):
        extra_fields_string = ", ".join([self._get_timestamp_outer_select()] + (extra_fields or []))
        return (
            FUNNEL_PERSONS_BY_STEP_SQL.format(
                offset=self._filter.offset,
                steps_per_person_query=self.get_step_counts_query(),
                persons_steps=self._get_funnel_person_step_condition(),
                extra_fields=extra_fields_string,
                limit="" if self._no_actor_limit else "LIMIT %(limit)s",
            ),
            self.params,
        )
