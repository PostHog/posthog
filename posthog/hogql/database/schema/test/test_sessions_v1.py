import pytest
from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.database.schema.sessions_v1 import (
    get_lazy_session_table_properties_v1,
    get_lazy_session_table_values_v1,
)
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.models.property_definition import PropertyType
from posthog.models.utils import uuid7
from posthog.schema import HogQLQueryModifiers, BounceRatePageViewMode, SessionTableVersion
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)


class TestSessionsV1(ClickhouseTestMixin, APIBaseTest):
    def __execute(self, query):
        modifiers = HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V1)
        return execute_hogql_query(
            query=query,
            team=self.team,
            modifiers=modifiers,
        )

    def test_select_star(self):
        session_id = "session_test_select_star"

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com", "$session_id": session_id},
        )

        response = self.__execute(
            parse_select(
                "select * from sessions where session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        self.assertEqual(
            len(response.results or []),
            1,
        )

    @pytest.mark.skip(reason="doesn't work, let's fix in V2")
    def test_select_event_sessions_star(self):
        session_id = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com", "$session_id": session_id},
        )

        response = self.__execute(
            parse_select(
                "select session.* from events where session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        self.assertEqual(
            len(response.results or []),
            1,
        )

    def test_select_session_replay_session_duration(self):
        session_id = str(uuid7())

        response = self.__execute(
            parse_select(
                "select raw_session_replay_events.session.duration from raw_session_replay_events",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        self.assertEqual(
            len(response.results or []),
            0,  # just making sure the query runs
        )

    def test_channel_type(self):
        session_id = "session_test_channel_type"

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"gad_source": "1", "$session_id": session_id},
        )

        response = self.__execute(
            parse_select(
                "select $channel_type from sessions where session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        result = (response.results or [])[0]
        self.assertEqual(
            result[0],
            "Paid Search",
        )

    def test_event_dot_session_dot_channel_type(self):
        session_id = "event_dot_session_dot_channel_type"

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"gad_source": "1", "$session_id": session_id},
        )

        response = self.__execute(
            parse_select(
                "select events.session.$channel_type from events where $session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        result = (response.results or [])[0]
        self.assertEqual(
            result[0],
            "Paid Search",
        )

    def test_events_session_dot_channel_type(self):
        session_id = "event_dot_session_dot_channel_type"

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"gad_source": "1", "$session_id": session_id},
        )

        response = self.__execute(
            parse_select(
                "select session.$channel_type from events where $session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        result = (response.results or [])[0]
        self.assertEqual(
            result[0],
            "Paid Search",
        )

    def test_persons_and_sessions_on_events(self):
        p1 = _create_person(distinct_ids=["d1"], team=self.team)
        p2 = _create_person(distinct_ids=["d2"], team=self.team)

        s1 = "session_test_persons_and_sessions_on_events_1"
        s2 = "session_test_persons_and_sessions_on_events_2"

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$session_id": s1, "utm_source": "source1"},
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d2",
            properties={"$session_id": s2, "utm_source": "source2"},
        )

        response = self.__execute(
            parse_select(
                "select events.person_id, session.$entry_utm_source from events where $session_id = {session_id} or $session_id = {session_id2} order by 2 asc",
                placeholders={"session_id": ast.Constant(value=s1), "session_id2": ast.Constant(value=s2)},
            ),
        )

        [row1, row2] = response.results or []
        self.assertEqual(row1, (p1.uuid, "source1"))
        self.assertEqual(row2, (p2.uuid, "source2"))

    @parameterized.expand([(BounceRatePageViewMode.UNIQ_URLS,), (BounceRatePageViewMode.COUNT_PAGEVIEWS,)])
    def test_bounce_rate(self, bounceRatePageViewMode):
        # person with 2 different sessions
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$session_id": "s1a", "$current_url": "https://example.com/1"},
            timestamp="2023-12-02",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$session_id": "s1a", "$current_url": "https://example.com/2"},
            timestamp="2023-12-03",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$session_id": "s1b", "$current_url": "https://example.com/3"},
            timestamp="2023-12-12",
        )
        # session with 1 pageview
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d2",
            properties={"$session_id": "s2", "$current_url": "https://example.com/4"},
            timestamp="2023-12-11",
        )
        # session with 1 pageview and 1 autocapture
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d3",
            properties={"$session_id": "s3", "$current_url": "https://example.com/5"},
            timestamp="2023-12-11",
        )
        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="d3",
            properties={"$session_id": "s3", "$current_url": "https://example.com/5"},
            timestamp="2023-12-11",
        )
        # short session with a pageleave
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d4",
            properties={"$session_id": "s4", "$current_url": "https://example.com/6"},
            timestamp="2023-12-11T12:00:00",
        )
        _create_event(
            event="$pageleave",
            team=self.team,
            distinct_id="d4",
            properties={"$session_id": "s4", "$current_url": "https://example.com/6"},
            timestamp="2023-12-11T12:00:01",
        )
        # long session with a pageleave
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d5",
            properties={"$session_id": "s5", "$current_url": "https://example.com/7"},
            timestamp="2023-12-11T12:00:00",
        )
        _create_event(
            event="$pageleave",
            team=self.team,
            distinct_id="d5",
            properties={"$session_id": "s5", "$current_url": "https://example.com/7"},
            timestamp="2023-12-11T12:00:11",
        )
        response = execute_hogql_query(
            parse_select(
                "select $is_bounce, session_id from sessions ORDER BY session_id",
            ),
            self.team,
            modifiers=HogQLQueryModifiers(
                bounceRatePageViewMode=bounceRatePageViewMode, sessionTableVersion=SessionTableVersion.V1
            ),
        )
        self.assertEqual(
            [
                (0, "s1a"),
                (1, "s1b"),
                (1, "s2"),
                (0, "s3"),
                (1, "s4"),
                (0, "s5"),
            ],
            response.results or [],
        )

    def test_can_use_v1_and_v2_fields(self):
        session_id = "session_test_can_use_v1_and_v2_fields"

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={
                "$current_url": "https://example.com/pathname",
                "$pathname": "/pathname",
                "$session_id": session_id,
            },
        )

        response = self.__execute(
            parse_select(
                """
                select
                    $session_duration,
                    duration,
                    $end_current_url,
                    $exit_current_url,
                    $end_pathname,
                    $exit_pathname
                from sessions
                where session_id = {session_id}
                """,
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        assert response.results == [
            (0, 0, "https://example.com/pathname", "https://example.com/pathname", "/pathname", "/pathname")
        ]


class TestGetLazySessionProperties(ClickhouseTestMixin, APIBaseTest):
    def test_all(self):
        results = get_lazy_session_table_properties_v1(None)
        self.assertEqual(len(results), 19)
        self.assertEqual(
            results[0],
            {
                "id": "$start_timestamp",
                "is_numerical": False,
                "is_seen_on_filtered_events": None,
                "name": "$start_timestamp",
                "property_type": PropertyType.Datetime,
                "tags": [],
            },
        )

    def test_source(self):
        results = get_lazy_session_table_properties_v1("source")
        self.assertEqual(
            results,
            [
                {
                    "id": "$entry_utm_source",
                    "is_numerical": False,
                    "is_seen_on_filtered_events": None,
                    "name": "$entry_utm_source",
                    "property_type": PropertyType.String,
                    "tags": [],
                },
                {
                    "id": "$entry_gad_source",
                    "is_numerical": False,
                    "is_seen_on_filtered_events": None,
                    "name": "$entry_gad_source",
                    "property_type": PropertyType.String,
                    "tags": [],
                },
            ],
        )

    def test_entry_utm(self):
        results = get_lazy_session_table_properties_v1("entry utm")
        self.assertEqual(
            [result["name"] for result in results],
            ["$entry_utm_source", "$entry_utm_campaign", "$entry_utm_medium", "$entry_utm_term", "$entry_utm_content"],
        )

    def test_can_get_values_for_all(self):
        results = get_lazy_session_table_properties_v1(None)
        for prop in results:
            get_lazy_session_table_values_v1(key=prop["id"], team=self.team, search_term=None)
