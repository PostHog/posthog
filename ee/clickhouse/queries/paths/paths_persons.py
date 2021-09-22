from typing import cast

from ee.clickhouse.queries.paths.paths import ClickhousePaths
from ee.clickhouse.sql.funnels.funnel import FUNNEL_PERSONS_BY_STEP_SQL
from posthog.models import Person
from posthog.models.filters.filter import Filter


class ClickhousePathsPersons(ClickhousePaths):
    def get_query(self):

        paths_per_person_query = self.get_paths_per_person_query()
        person_path_filter = self.get_person_path_filter()
        paths_funnel_cte = ""

        if self.should_query_funnel():
            paths_funnel_cte = self.get_path_query_funnel_cte(cast(Filter, self._funnel_filter))

        self.params["limit"] = self._filter.limit
        self.params["offset"] = self._filter.offset

        return f"""
            {paths_funnel_cte}
            SELECT DISTINCT person_id
            FROM (
                {paths_per_person_query}
            )
            WHERE {person_path_filter}
            ORDER BY person_id
            LIMIT %(limit)s
            OFFSET %(offset)s
        """

    def get_person_path_filter(self) -> str:
        conditions = []
        if self._filter.path_start_key:
            conditions.append("last_path_key = %(path_start_key)s")
            self.params["path_start_key"] = self._filter.path_start_key

        if self._filter.path_end_key:
            conditions.append("path_key = %(path_end_key)s")
            self.params["path_end_key"] = self._filter.path_end_key

        if conditions:
            return " AND ".join(conditions)

        return "1=1"

    def _format_results(self, results):
        people = Person.objects.filter(team_id=self._team.pk, uuid__in=[val[0] for val in results])

        from posthog.api.person import PersonSerializer

        return PersonSerializer(people, many=True).data, len(results) > cast(int, self._filter.limit) - 1
