from typing import List, Optional, cast

from ee.clickhouse.queries.actor_base_query import ActorBaseQuery
from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel
from ee.clickhouse.sql.funnels.funnel import FUNNEL_PERSONS_BY_STEP_SQL
from posthog.models import Person
from posthog.models.filters.mixins.utils import cached_property


class ClickhouseFunnelPersons(ClickhouseFunnel, ActorBaseQuery):
    @cached_property
    def is_aggregating_by_groups(self) -> bool:
        return self._filter.aggregation_group_type_index is not None

    def get_query(self, extra_fields: Optional[List[str]] = None):
        return self.actor_query(extra_fields)

    def actor_query(self, extra_fields: Optional[List[str]] = None):
        extra_fields_string = ", ".join([self._get_timestamp_outer_select()] + (extra_fields or []))
        return (
            FUNNEL_PERSONS_BY_STEP_SQL.format(
                offset=self._filter.offset,
                steps_per_person_query=self.get_step_counts_query(),
                persons_steps=self._get_funnel_person_step_condition(),
                extra_fields=extra_fields_string,
                limit="" if self._no_person_limit else "LIMIT %(limit)s",
            ),
            self.params,
        )

    def _format_results(self, results):
        people = Person.objects.filter(team_id=self._team.pk, uuid__in=[val[0] for val in results])

        from posthog.api.person import PersonSerializer

        return PersonSerializer(people, many=True).data, len(results) > cast(int, self._filter.limit) - 1
