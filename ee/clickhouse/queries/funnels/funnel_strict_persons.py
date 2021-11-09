from typing import cast

from ee.clickhouse.queries.funnels.funnel_strict import ClickhouseFunnelStrict
from ee.clickhouse.sql.funnels.funnel import FUNNEL_PERSONS_BY_STEP_SQL
from posthog.models import Person


class ClickhouseFunnelStrictPersons(ClickhouseFunnelStrict):
    def get_query(self):
        return FUNNEL_PERSONS_BY_STEP_SQL.format(
            offset=self._filter.offset,
            steps_per_person_query=self.get_step_counts_query(),
            persons_steps=self._get_funnel_person_step_condition(),
            extra_fields=self._get_timestamp_outer_select(),
            limit="" if self._no_person_limit else "LIMIT %(limit)s",
        )

    def _format_results(self, results):
        people = Person.objects.filter(team_id=self._team.pk, uuid__in=[val[0] for val in results])

        from posthog.api.person import PersonSerializer

        return PersonSerializer(people, many=True).data, len(results) > cast(int, self._filter.limit) - 1
