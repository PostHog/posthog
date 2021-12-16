from typing import cast

from rest_framework.exceptions import ValidationError

from ee.clickhouse.queries.actor_base_query import ActorBaseQuery
from ee.clickhouse.queries.funnels.funnel_trends import TIMESTAMP_FORMAT, ClickhouseFunnelTrends
from ee.clickhouse.queries.util import get_trunc_func_ch
from ee.clickhouse.sql.funnels.funnel import FUNNEL_PERSONS_BY_STEP_SQL
from posthog.constants import DROP_OFF, ENTRANCE_PERIOD_START
from posthog.models.filters.filter import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.person import Person


class ClickhouseFunnelTrendsActors(ClickhouseFunnelTrends, ActorBaseQuery):
    _filter: Filter

    @cached_property
    def is_aggregating_by_groups(self) -> bool:
        return self._filter.aggregation_group_type_index is not None

    def actor_query(self):
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

        _, reached_to_step_count_condition, did_not_reach_to_step_count_condition = self.get_steps_reached_conditions()

        return (
            FUNNEL_PERSONS_BY_STEP_SQL.format(
                steps_per_person_query=step_counts_query,
                persons_steps=did_not_reach_to_step_count_condition if drop_off else reached_to_step_count_condition,
                extra_fields="",
                limit="" if self._no_actor_limit else "LIMIT %(limit)s",
                offset="" if self._no_actor_limit else "OFFSET %(offset)s",
            ),
            self.params,
        )
