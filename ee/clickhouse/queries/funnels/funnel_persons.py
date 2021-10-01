from typing import Optional, cast

from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel
from ee.clickhouse.sql.funnels.funnel import FUNNEL_PERSONS_BY_STEP_SQL
from posthog.models import Person
from posthog.models.filters.filter import Filter
from posthog.models.team import Team


class ClickhouseFunnelPersons(ClickhouseFunnel):

    _no_limit: Optional[bool]  # used when paths are querying for filter people

    def __init__(
        self,
        filter: Filter,
        team: Team,
        include_timestamp: Optional[bool] = None,
        include_preceding_timestamp: Optional[bool] = None,
        no_limit: Optional[bool] = False,
    ) -> None:
        self._no_limit = no_limit
        super().__init__(
            filter, team, include_timestamp=include_timestamp, include_preceding_timestamp=include_preceding_timestamp
        )

    def get_query(self):
        return FUNNEL_PERSONS_BY_STEP_SQL.format(
            offset=self._filter.offset,
            steps_per_person_query=self.get_step_counts_query(),
            persons_steps=self._get_funnel_person_step_condition(),
            extra_fields=self._get_timestamp_outer_select(),
            limit="" if self._no_limit else "LIMIT %(limit)s",
        )

    def _format_results(self, results):
        people = Person.objects.filter(team_id=self._team.pk, uuid__in=[val[0] for val in results])

        from posthog.api.person import PersonSerializer

        return PersonSerializer(people, many=True).data, len(results) > cast(int, self._filter.limit) - 1
