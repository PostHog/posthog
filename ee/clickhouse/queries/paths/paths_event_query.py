from ee.clickhouse.queries.event_query import EnterpriseEventQuery
from posthog.queries.paths.paths_event_query import PathEventQuery


class ClickhousePathEventQuery(PathEventQuery, EnterpriseEventQuery):
    def _determine_should_join_persons(self) -> None:
        EnterpriseEventQuery._determine_should_join_persons(self)
        if self._using_person_on_events:
            self._should_join_distinct_ids = False
            self._should_join_persons = False
