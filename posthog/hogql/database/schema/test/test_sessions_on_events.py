from datetime import UTC

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, snapshot_clickhouse_queries

from posthog.schema import HogQLQueryModifiers, SessionsOnEventsMode, SessionTableVersion

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

from posthog.models.utils import uuid7


@snapshot_clickhouse_queries
class TestSessionsOnEvents(ClickhouseTestMixin, APIBaseTest):
    snapshot_replace_all_numbers = True

    def __execute(self, query, sessions_on_events_mode=SessionsOnEventsMode.V3):
        modifiers = HogQLQueryModifiers(
            sessionTableVersion=SessionTableVersion.V3,
            sessionsOnEventsMode=sessions_on_events_mode,
        )
        return execute_hogql_query(
            query=query,
            team=self.team,
            modifiers=modifiers,
        )

    def __print_query(self, query, sessions_on_events_mode=SessionsOnEventsMode.V3):
        modifiers = HogQLQueryModifiers(
            sessionTableVersion=SessionTableVersion.V3,
            sessionsOnEventsMode=sessions_on_events_mode,
        )
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            modifiers=modifiers,
        )
        query_str, _ = prepare_and_print_ast(query, context, "clickhouse")
        return query_str

    def test_no_override_join_without_session_access(self):
        query_str = self.__print_query(
            parse_select("select event, timestamp from events limit 1"),
        )

        # Should NOT contain a join to raw_sessions_overrides_v3
        self.assertNotIn("raw_sessions_overrides_v3", query_str)
        self.assertNotIn("session_overrides", query_str)

    def test_override_join_with_session_access(self):
        query_str = self.__print_query(
            parse_select("select session.$entry_current_url from events limit 1"),
        )

        # Should contain a join to raw_sessions_overrides_v3
        self.assertIn("raw_sessions_overrides_v3", query_str)
        # Should use argMinMerge for entry fields
        self.assertIn("argMinMerge", query_str)
        # Should group by session_id_v7
        self.assertIn("session_id_v7", query_str)

    def test_sessions_on_events_disabled(self):
        query_str = self.__print_query(
            parse_select("select session.$entry_current_url from events limit 1"),
            sessions_on_events_mode=SessionsOnEventsMode.DISABLED,
        )

        # Should join to sessions table (not overrides)
        self.assertIn("raw_sessions_v3", query_str)
        # Should NOT use the overrides table
        self.assertNotIn("raw_sessions_overrides_v3", query_str)
        self.assertNotIn("session_overrides", query_str)

    def test_session_duration(self):
        session_id = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com", "$session_id": session_id},
            timestamp="2024-01-01 00:00:00",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com/page2", "$session_id": session_id},
            timestamp="2024-01-01 00:05:00",  # 5 mins later
        )

        response = self.__execute(
            parse_select(
                "select session.duration from events where $session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        results = response.results or []
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][0], 5 * 60)

    def test_session_entry_url(self):
        session_id = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com/first", "$session_id": session_id},
            timestamp="2024-01-01 00:00:00",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com/second", "$session_id": session_id},
            timestamp="2024-01-01 00:01:00",
        )

        response = self.__execute(
            parse_select(
                "select session.$entry_current_url from events where $session_id = {session_id} order by timestamp",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        results = response.results or []
        self.assertEqual(len(results), 2)
        # Both events should have the same entry URL (first page)
        self.assertEqual(results[0][0], "https://example.com/first")
        self.assertEqual(results[1][0], "https://example.com/first")

    def test_session_timestamps(self):
        session_id = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$session_id": session_id},
            timestamp="2024-01-01 00:00:00",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$session_id": session_id},
            timestamp="2024-01-01 00:05:00",
        )

        response = self.__execute(
            parse_select(
                "select session.$start_timestamp, session.$end_timestamp from events where $session_id = {session_id} order by timestamp limit 1",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        results = response.results or []
        self.assertEqual(len(results), 1)
        # Verify timestamps match the event timestamps
        from datetime import datetime

        start_ts = results[0][0]
        end_ts = results[0][1]
        self.assertIsNotNone(start_ts)
        self.assertIsNotNone(end_ts)
        # Start should be 2024-01-01 00:00:00, end should be 2024-01-01 00:05:00
        self.assertEqual(start_ts.replace(tzinfo=UTC), datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC))
        self.assertEqual(end_ts.replace(tzinfo=UTC), datetime(2024, 1, 1, 0, 5, 0, tzinfo=UTC))

    def test_session_attribution_fields(self):
        session_id = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={
                "$session_id": session_id,
                "utm_source": "google",
                "utm_campaign": "summer_sale",
                "utm_medium": "cpc",
            },
            timestamp="2024-01-01 00:00:00",
        )

        response = self.__execute(
            parse_select(
                "select session.$entry_utm_source, session.$entry_utm_campaign, session.$entry_utm_medium from events where $session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        results = response.results or []
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], "google")
        self.assertEqual(results[0][1], "summer_sale")
        self.assertEqual(results[0][2], "cpc")

    def test_multiple_session_properties(self):
        session_id = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={
                "$session_id": session_id,
                "$current_url": "https://example.com/entry",
                "utm_source": "google",
            },
            timestamp="2024-01-01 00:00:00",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={
                "$session_id": session_id,
                "$current_url": "https://example.com/exit",
            },
            timestamp="2024-01-01 00:05:00",
        )

        response = self.__execute(
            parse_select(
                "select session.$entry_current_url, session.$end_current_url, session.$entry_utm_source from events where $session_id = {session_id} limit 1",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        results = response.results or []
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], "https://example.com/entry")
        self.assertEqual(results[0][1], "https://example.com/exit")
        self.assertEqual(results[0][2], "google")

    def test_session_property_in_where_clause(self):
        session_id_google = str(uuid7())
        session_id_facebook = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$session_id": session_id_google, "utm_source": "google"},
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d2",
            properties={"$session_id": session_id_facebook, "utm_source": "facebook"},
        )

        response = self.__execute(
            parse_select("select event from events where session.$entry_utm_source = 'google'"),
        )

        results = response.results or []
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], "$pageview")

    def test_session_duration_aggregation(self):
        s1 = str(uuid7())
        s2 = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$session_id": s1},
            timestamp="2024-01-01 00:00:00",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$session_id": s1},
            timestamp="2024-01-01 00:10:00",  # 10 mins later
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d2",
            properties={"$session_id": s2},
            timestamp="2024-01-01 00:20:00",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d2",
            properties={"$session_id": s2},
            timestamp="2024-01-01 00:40:00",  # 20 mins later
        )

        response = self.__execute(
            parse_select(
                "select avg(session.duration) from events",
                placeholders={"session_id": ast.Constant(value=s1)},
            ),
        )

        results = response.results or []
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], 15 * 60)  # 15 is the average of 10 and 20

    def test_can_use_session_on_events_and_person_overrides_together(self):
        session_id = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com", "$session_id": session_id},
            timestamp="2024-01-01 00:00:00",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com/page2", "$session_id": session_id},
            timestamp="2024-01-01 00:05:00",  # 5 mins later
        )
        response = self.__execute(
            parse_select(
                "select session.duration, person_id from events where $session_id = {session_id} limit 1",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        results = response.results or []
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], 5 * 60)

    def test_can_alias_table(self):
        session_id = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com", "$session_id": session_id},
            timestamp="2024-01-01 00:00:00",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com/page2", "$session_id": session_id},
            timestamp="2024-01-01 00:05:00",  # 5 mins later
        )

        response = self.__execute(
            parse_select(
                "select e.session.duration from events as e where $session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        results = response.results or []
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][0], 5 * 60)
