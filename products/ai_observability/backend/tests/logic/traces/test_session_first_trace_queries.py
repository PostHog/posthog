from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Organization, Team

from products.ai_observability.backend.logic.traces import session_first_trace_queries
from products.ai_observability.backend.logic.traces.session_first_trace_queries import (
    SESSION_TITLE_TRACES_QUERY_NAME,
    SessionFirstTrace,
    load_session_first_traces,
)

from .test_trace_selection_queries import at, seed


def event(name: str, trace_id: str, minutes: int, session_id: str | None = None, **properties: Any) -> dict[str, Any]:
    session = {} if session_id is None else {"$ai_session_id": session_id}
    return {"event": name, "trace_id": trace_id, "minutes": minutes, "properties": {**session, **properties}}


class TestSessionFirstTraceQueries(ClickhouseTestMixin, BaseTest):
    def _first(self, *, since_minutes: int = -60, include_support_traces: bool = False) -> str | None:
        firsts = load_session_first_traces(
            self.team,
            self.user,
            ["session-a"],
            since=at(since_minutes),
            include_support_traces=include_support_traces,
            name=SESSION_TITLE_TRACES_QUERY_NAME,
        )
        return firsts["session-a"].trace_id if "session-a" in firsts else None

    def test_a_trace_that_names_its_session_late_is_first_when_it_started_first(self) -> None:
        seed(
            self.team,
            [
                event("$ai_span", "late-tagged", 0),
                event("$ai_generation", "late-tagged", 5, "session-a"),
                event("$ai_generation", "tagged", 2, "session-a"),
            ],
        )

        assert self._first() == "late-tagged"

    @parameterized.expand([("left out", False, "customer"), ("included", True, "support")])
    def test_support_traces_never_crowd_out_the_first_trace(
        self, _name: str, include_support_traces: bool, expected: str
    ) -> None:
        seed(
            self.team,
            [
                event("$ai_generation", "support", 0, "session-a", ai_support_impersonated="true"),
                event("$ai_generation", "customer", 1, "session-a"),
            ],
        )

        with patch.object(session_first_trace_queries, "FIRST_TRACE_CANDIDATES", 1):
            assert self._first(include_support_traces=include_support_traces) == expected

    def test_an_event_without_a_trace_id_never_makes_untraced_events_the_first_trace(self) -> None:
        seed(
            self.team,
            [
                event("$ai_generation", "", -5),
                event("$ai_generation", "", 1, "session-a"),
                event("$ai_generation", "traced", 2, "session-a"),
            ],
        )

        assert self._first() == "traced"

    @parameterized.expand([("feedback", "$ai_feedback"), ("metric", "$ai_metric")])
    def test_a_trace_named_only_on_an_activity_event_is_first_from_its_trace_events(
        self, _name: str, activity_event: str
    ) -> None:
        seed(
            self.team,
            [
                {**event("$ai_generation", "named-on-activity", 0), "distinct_id": "customer"},
                {**event(activity_event, "named-on-activity", 3, "session-a"), "distinct_id": "reviewer"},
                event("$ai_generation", "tagged", 1, "session-a"),
            ],
        )

        firsts = load_session_first_traces(
            self.team,
            self.user,
            ["session-a"],
            since=at(-60),
            include_support_traces=False,
            name=SESSION_TITLE_TRACES_QUERY_NAME,
        )

        assert firsts == {"session-a": SessionFirstTrace(trace_id="named-on-activity", distinct_id="customer")}

    def test_a_trace_before_the_cutoff_is_not_read(self) -> None:
        seed(
            self.team,
            [event("$ai_generation", "too-old", -10, "session-a"), event("$ai_generation", "kept", 0, "session-a")],
        )

        assert self._first(since_minutes=-5) == "kept"

    def test_another_teams_trace_is_never_first(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other organization"))
        seed(other_team, [event("$ai_generation", "foreign", 0, "session-a")])
        seed(self.team, [event("$ai_generation", "mine", 1, "session-a")])

        assert self._first() == "mine"
