from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel
from ee.clickhouse.sql.funnels.funnel import FUNNEL_PERSONS_BY_STEP_SQL
from posthog.models import Person


class ClickhouseFunnelPersons(ClickhouseFunnel):
    def run(self, *args, **kwargs):
        if len(self._filter.entities) == 0:
            return []

        results = self._exec_query()
        return self._format_results(results), len(results) > self._filter.limit - 1

    def get_query(self):
        return FUNNEL_PERSONS_BY_STEP_SQL.format(
            offset=self._filter.offset,
            steps_per_person_query=self.get_step_counts_query(),
            persons_steps=self._get_funnel_person_step_condition(),
        )

    def _format_results(self, results):
        people = Person.objects.filter(team_id=self._team.pk, uuid__in=[val[0] for val in results])

        from posthog.api.person import PersonSerializer

        return PersonSerializer(people, many=True).data
