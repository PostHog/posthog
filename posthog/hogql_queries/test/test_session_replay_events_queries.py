from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.schema import HogQLQuery
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL
from posthog.test.base import ClickhouseTestMixin, APIBaseTest, QueryMatchingTest, snapshot_clickhouse_queries


class TestSessionReplayEventsHogQLQueries(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def tearDown(self):
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())

    def setUp(self):
        super().setUp()

        produce_replay_summary(
            team_id=self.team.id,
            session_id="session_id_one",
            distinct_id="distinct_id_one",
            mouse_activity_count=100,
        )
        produce_replay_summary(
            team_id=self.team.id,
            session_id="session_id_two",
            distinct_id="distinct_id_two",
            mouse_activity_count=200,
        )
        produce_replay_summary(
            team_id=self.team.id,
            session_id="session_id_two",
            distinct_id="distinct_id_two",
            mouse_activity_count=300,
        )

    @snapshot_clickhouse_queries
    def test_session_replay_events_table_does_not_need_to_be_grouped_by_session_id_explicitly(self):
        runner = HogQLQueryRunner(
            team=self.team,
            query=HogQLQuery(
                query="""
            select session_id, sum(mouse_activity_count) as mouse_activity_count
            from session_replay_events
            -- this table is always implicitly grouped by session id
            order by mouse_activity_count desc
            """
            ),
        )

        response = runner.calculate()
        assert response.results == [("session_id_two", 500), ("session_id_one", 100)]

    @snapshot_clickhouse_queries
    def test_session_replay_events_table_is_always_grouped_by_session_id(self):
        # test that the "not raw" table is always grouped by session id
        runner = HogQLQueryRunner(
            team=self.team,
            query=HogQLQuery(
                query="""
            select distinct_id, sum(mouse_activity_count) as mouse_activity_count
            from session_replay_events
            group by distinct_id -- this table is also always implicitly grouped by session id
            order by mouse_activity_count desc
            """
            ),
        )

        response = runner.calculate()
        assert response.results == [("distinct_id_two", 500), ("distinct_id_one", 100)]
