from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from django.utils.timezone import now

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.models.event.sql import TRUNCATE_EVENTS_TABLE_SQL
from posthog.models.utils import uuid7
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL


@freeze_time("2021-01-01T13:46:23")
class TestFilterSessionReplaysBySessions(ClickhouseTestMixin, APIBaseTest):
    session_with_one_hour = str(uuid7("2021-01-01T10"))
    session_with_different_session_and_replay_duration = str(uuid7("2021-01-01T11"))
    session_with_no_events = str(uuid7("2021-01-01T12"))

    def setUp(self):
        super().setUp()

        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())
        sync_execute(TRUNCATE_EVENTS_TABLE_SQL())

        # 1-hour session replay
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="d1",
            session_id=self.session_with_one_hour,
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com", "$session_id": self.session_with_one_hour},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com", "$session_id": self.session_with_one_hour},
            timestamp=now() + timedelta(hours=1),
        )

        # 1-hour session replay
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="d1",
            session_id=self.session_with_different_session_and_replay_duration,
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={
                "$current_url": "https://different.com",
                "$session_id": self.session_with_different_session_and_replay_duration,
            },
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={
                "$current_url": "https://different.com",
                "$session_id": self.session_with_different_session_and_replay_duration,
            },
            # timestamp is two hours in the future
            timestamp=now() + timedelta(hours=2),
        )

        produce_replay_summary(
            team_id=self.team.pk, distinct_id="d1", session_id=self.session_with_no_events, log_messages=None
        )

    @snapshot_clickhouse_queries
    def test_select_by_duration_without_session_filter(self):
        response = execute_hogql_query(
            parse_select(
                """
                select distinct session_id
                from raw_session_replay_events
                group by session_id
                having dateDiff('second', min(min_first_timestamp), max(max_last_timestamp)) = 3600
                order by session_id asc""",
                placeholders={"event_name": ast.Constant(value="$pageview")},
            ),
            self.team,
        )

        assert response.results == [
            (self.session_with_one_hour,),
            (self.session_with_different_session_and_replay_duration,),
            (self.session_with_no_events,),
        ]

    @snapshot_clickhouse_queries
    def test_select_by_duration_with_session_duration_filter(self):
        response = execute_hogql_query(
            parse_select(
                """
                select distinct session_id
                from raw_session_replay_events
                where session.duration > 3600
                group by session_id
                having dateDiff('second', min(min_first_timestamp), max(max_last_timestamp)) = 3600
                order by session_id asc""",
                placeholders={"event_name": ast.Constant(value="$pageview")},
            ),
            self.team,
        )

        assert response.results == [
            (self.session_with_different_session_and_replay_duration,),
        ]


@freeze_time("2021-01-01T13:46:23")
class TestFilterSessionReplaysByEvents(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()

        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())

        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="d1",
            session_id="session_with_example_com_pageview",
            ensure_analytics_event_in_session=False,  # Handling events ourselves in this suite
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com", "$session_id": "session_with_example_com_pageview"},
        )

        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="d1",
            session_id="session_with_different_com_pageview",
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://different.com", "$session_id": "session_with_different_com_pageview"},
        )

        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="d1",
            session_id="session_with_no_events",
            log_messages=None,
            ensure_analytics_event_in_session=False,  # Handling events ourselves in this suite
        )

    @snapshot_clickhouse_queries
    def test_select_by_event(self):
        response = execute_hogql_query(
            parse_select(
                "select distinct session_id from raw_session_replay_events where events.event = {event_name} order by session_id asc",
                placeholders={"event_name": ast.Constant(value="$pageview")},
            ),
            self.team,
        )

        assert response.results == [
            ("session_with_different_com_pageview",),
            ("session_with_example_com_pageview",),
        ]

    @snapshot_clickhouse_queries
    def test_select_by_event_property(self):
        response = execute_hogql_query(
            parse_select(
                "select distinct session_id from raw_session_replay_events where events.properties.$current_url like {url} order by session_id asc",
                placeholders={"url": ast.Constant(value="%example.com%")},
            ),
            self.team,
        )

        assert response.results == [
            ("session_with_example_com_pageview",),
        ]

    @snapshot_clickhouse_queries
    def test_select_by_subquery_on_event_property_without_join(self):
        # regression test: so we can manually check the clickhouse snapshot
        # to assert that a subquery like this
        # doesn't accidentally become a join
        response = execute_hogql_query(
            parse_select(
                """
                select distinct session_id
                from raw_session_replay_events
                where session_id in (
                    select $session_id
                    from events
                    where events.properties.$current_url like {url}
                )
                order by session_id asc""",
                placeholders={"url": ast.Constant(value="%example.com%")},
            ),
            self.team,
        )

        assert response.results == [
            ("session_with_example_com_pageview",),
        ]

        assert response.results == [
            ("session_with_example_com_pageview",),
        ]

    @snapshot_clickhouse_queries
    def test_select_event_property(self):
        response = execute_hogql_query(
            parse_select(
                "select session_id, any(events.properties.$current_url) from raw_session_replay_events group by session_id order by session_id asc",
            ),
            self.team,
        )

        assert response.results == [
            (
                "session_with_different_com_pageview",
                "https://different.com",
            ),
            (
                "session_with_example_com_pageview",
                "https://example.com",
            ),
        ]


@freeze_time("2021-01-01T13:46:23")
class TestFilterSessionReplaysByPerson(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()

        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())

        self._p1 = _create_person(distinct_ids=["d1"], team=self.team)

        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="d1",
            session_id="session_for_person_p1",
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com", "$session_id": "session_for_person_p1"},
        )

        self._p2 = _create_person(distinct_ids=["d2"], team=self.team, properties={"person_property": True})

        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="d2",
            session_id="session_with_person_with_person_property",
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d2",
            properties={
                "$current_url": "https://different.com",
                "$session_id": "session_with_person_with_person_property",
            },
        )

        flush_persons_and_events()

    @snapshot_clickhouse_queries
    def test_select_by_replay_person(self):
        response = execute_hogql_query(
            parse_select(
                "select distinct session_id from raw_session_replay_events where person.id = {person_id} order by session_id asc",
                placeholders={"person_id": ast.Constant(value=self._p1.uuid)},
            ),
            self.team,
        )

        assert response.results == [
            ("session_for_person_p1",),
        ]

    @snapshot_clickhouse_queries
    def test_select_by_person_distinct_id(self):
        response = execute_hogql_query(
            parse_select(
                "select distinct session_id from raw_session_replay_events where pdi.distinct_id = {person_distinct_id} order by session_id asc",
                placeholders={"person_distinct_id": ast.Constant(value="d1")},
            ),
            self.team,
        )

        assert response.results == [
            ("session_for_person_p1",),
        ]

    @snapshot_clickhouse_queries
    def test_select_by_event_person(self):
        response = execute_hogql_query(
            parse_select(
                "select distinct session_id from raw_session_replay_events where ifNull(events.person.properties.person_property, 'false') = {prop_value} order by session_id asc",
                placeholders={"prop_value": ast.Constant(value="true")},
            ),
            self.team,
        )

        assert response.results == [
            ("session_with_person_with_person_property",),
        ]

    @snapshot_clickhouse_queries
    def test_select_person_property(self):
        response = execute_hogql_query(
            parse_select(
                "select session_id, any(person.properties.person_property) from raw_session_replay_events group by session_id order by session_id asc",
            ),
            self.team,
        )

        assert response.results == [
            ("session_for_person_p1", None),
            # todo: why is this the string true?
            ("session_with_person_with_person_property", "true"),
        ]

    @snapshot_clickhouse_queries
    def test_select_where_person_property_without_join_optimization(self):
        response = execute_hogql_query(
            parse_select(
                """
                select session_id, any(person.properties.person_property)
                from raw_session_replay_events
                where person.properties.person_property = 'true'
                group by session_id order by session_id asc
                """,
            ),
            self.team,
            modifiers=HogQLQueryModifiers(optimizeJoinedFilters=False),
        )

        assert response.results == [
            ("session_with_person_with_person_property", "true"),
        ]

    @snapshot_clickhouse_queries
    def test_select_where_person_property_with_join_optimization(self):
        response = execute_hogql_query(
            parse_select(
                """
                select session_id, any(person.properties.person_property)
                from raw_session_replay_events
                where person.properties.person_property = 'true'
                group by session_id order by session_id asc
                """,
            ),
            self.team,
            modifiers=HogQLQueryModifiers(optimizeJoinedFilters=True),
        )

        assert response.results == [
            ("session_with_person_with_person_property", "true"),
        ]


@freeze_time("2021-01-01T13:46:23")
class TestFilterSessionReplaysByConsoleLogs(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()

        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())

        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="d1",
            session_id="session_with_info_and_error_messages",
            log_messages={
                "info": ["This is an info message"],
                "error": ["This is a generic message"],
            },
        )

        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="d1",
            session_id="session_with_only_info_messages",
            log_messages={
                "info": ["This is a generic message"],
            },
        )

        produce_replay_summary(
            team_id=self.team.pk, distinct_id="d1", session_id="session_with_no_log_messages", log_messages=None
        )

    @snapshot_clickhouse_queries
    def test_select_by_console_log_text(self):
        response = execute_hogql_query(
            parse_select(
                "select distinct session_id from raw_session_replay_events where console_logs.message = {log_message} order by session_id asc",
                placeholders={"log_message": ast.Constant(value="This is a generic message")},
            ),
            self.team,
        )

        assert response.results == [("session_with_info_and_error_messages",), ("session_with_only_info_messages",)]

    @snapshot_clickhouse_queries
    def test_select_by_console_log_text_and_level(self):
        response = execute_hogql_query(
            parse_select(
                "select distinct session_id from raw_session_replay_events where console_logs.message = {log_message} and console_logs.level = {log_level} order by session_id asc",
                placeholders={
                    "log_message": ast.Constant(value="This is a generic message"),
                    "log_level": ast.Constant(value="error"),
                },
            ),
            self.team,
        )

        assert response.results == [("session_with_info_and_error_messages",)]

    @snapshot_clickhouse_queries
    def test_select_log_text(self):
        response = execute_hogql_query(
            parse_select(
                "select distinct console_logs.message from raw_session_replay_events where console_logs.level = {log_level} order by session_id asc",
                placeholders={
                    "log_level": ast.Constant(value="info"),
                },
            ),
            self.team,
        )

        assert response.results == [("This is an info message",), ("This is a generic message",)]
