from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)


class TestReferringDomainType(ClickhouseTestMixin, APIBaseTest):
    def test_select_star(self):
        session_id = "session_test_select_star"

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com", "$session_id": session_id},
        )

        response = execute_hogql_query(
            parse_select(
                "select * from sessions where session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
            self.team,
        )

        self.assertEqual(
            len(response.results or []),
            1,
        )

    def test_channel_type(self):
        session_id = "session_test_channel_type"

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"gad_source": "1", "$session_id": session_id},
        )

        response = execute_hogql_query(
            parse_select(
                "select $channel_type from sessions where session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
            self.team,
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

        response = execute_hogql_query(
            parse_select(
                "select events.session.$channel_type from events where $session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
            self.team,
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

        response = execute_hogql_query(
            parse_select(
                "select session.$channel_type from events where $session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
            self.team,
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

        response = execute_hogql_query(
            parse_select(
                "select events.person_id, session.$initial_utm_source from events where $session_id = {session_id} or $session_id = {session_id2} order by 2 asc",
                placeholders={"session_id": ast.Constant(value=s1), "session_id2": ast.Constant(value=s2)},
            ),
            self.team,
        )

        [row1, row2] = response.results or []
        self.assertEqual(row1, (p1.uuid, "source1"))
        self.assertEqual(row2, (p2.uuid, "source2"))
