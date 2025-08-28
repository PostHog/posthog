import pytest
from posthog.test.base import APIBaseTest, ClickhouseDestroyTablesMixin, ClickhouseTestMixin, _create_event

from django.db.utils import IntegrityError

from parameterized import parameterized

from posthog.schema import BounceRatePageViewMode, HogQLQueryModifiers, SessionTableVersion

from posthog.hogql import ast
from posthog.hogql.database.schema.sessions_v1 import (
    get_lazy_session_table_properties_v1,
    get_lazy_session_table_values_v1,
)
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Organization, Team
from posthog.models.property_definition import PropertyType
from posthog.models.sessions.sql import ALLOWED_TEAM_IDS
from posthog.models.utils import uuid7


class TestSessionsV1(ClickhouseDestroyTablesMixin, ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()

        # only certain team ids can insert events into this legacy sessions table, see sessions/sql.py for more info
        team_id = 2
        assert team_id in ALLOWED_TEAM_IDS

        self.organization = Organization.objects.create(name="Test Organization")
        try:
            self.team = Team.objects.create(organization=self.organization, id=team_id, pk=team_id)
        except IntegrityError:
            # For some reasons, in CI, the team is already created, so let's just get it from the database
            self.team = Team.objects.get(id=team_id)

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
        assert len(results) == 32
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

    def test_custom_channel_types(self):
        results = get_lazy_session_table_values_v1(key="$channel_type", team=self.team, search_term=None)
        # the custom channel types should be first, there's should be no duplicates, and any custom rules for existing
        # channel types should be bumped to the top
        assert results == [
            ["Cross Network"],
            ["Paid Search"],
            ["Paid Social"],
            ["Paid Video"],
            ["Paid Shopping"],
            ["Paid Unknown"],
            ["Direct"],
            ["Organic Search"],
            ["Organic Social"],
            ["Organic Video"],
            ["Organic Shopping"],
            ["Push"],
            ["SMS"],
            ["Audio"],
            ["Email"],
            ["Referral"],
            ["Affiliate"],
            ["Unknown"],
        ]
