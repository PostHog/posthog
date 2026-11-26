from datetime import timedelta
from typing import Any

import pytest
import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.models import Organization, Team
from posthog.models.event.util import bulk_create_events

from products.ai_observability.backend.logic.traces import session_queries
from products.ai_observability.backend.logic.traces.events_fallback import fallback_window
from products.ai_observability.backend.logic.traces.session_queries import (
    SessionFacts,
    load_session_facts,
    load_shared_session_facts,
)

from .test_trace_selection_queries import T0, at, seed


def event(
    event_name: str,
    trace_id: str,
    minutes: int,
    session_id: str | None = None,
    latency: float | None = None,
    props: dict[str, Any] | None = None,
) -> dict:
    session = {} if session_id is None else {"$ai_session_id": session_id}
    timing = {} if latency is None else {"$ai_latency": latency}
    return {
        "event": event_name,
        "trace_id": trace_id,
        "minutes": minutes,
        "properties": {**session, **timing, **(props or {})},
    }


def generation(
    trace_id: str,
    minutes: int,
    session_id: str | None = None,
    latency: float | None = None,
    props: dict[str, Any] | None = None,
) -> dict:
    return event("$ai_generation", trace_id, minutes, session_id, latency, props)


def root(
    trace_id: str,
    minutes: int,
    session_id: str | None = None,
    latency: float | None = None,
    props: dict[str, Any] | None = None,
) -> dict:
    return event("$ai_trace", trace_id, minutes, session_id, latency, props)


class TestSessionQueries(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        traveller = time_machine.travel(T0 + timedelta(days=1), tick=False)
        traveller.start()
        self.addCleanup(traveller.stop)

    def _facts(self, *session_ids: str, **kwargs: Any) -> dict[str, SessionFacts]:
        return load_session_facts(self.team, self.user, list(session_ids), since=at(-60), **kwargs)

    def test_totals_follow_trace_rules(self) -> None:
        seed(
            self.team,
            [
                root("t-root", 0, latency=5),
                generation(
                    "t-root",
                    1,
                    "s1",
                    latency=2,
                    props={"$ai_total_cost_usd": 0.01, "$ai_input_tokens": 10, "$ai_output_tokens": 4},
                ),
                generation(
                    "t-gens",
                    3,
                    "s1",
                    latency=1.5,
                    props={"$ai_total_cost_usd": 0.02, "$ai_input_tokens": 20, "$ai_cache_read_input_tokens": 7},
                ),
                generation("t-gens", 4, latency=2, props={"$ai_total_cost_usd": 0.03, "$ai_output_tokens": 6}),
                generation("t-other", 2, "s2", latency=100, props={"$ai_total_cost_usd": 9}),
            ],
        )

        facts = self._facts("s1")["s1"]

        assert facts.turn_count == 2
        assert facts.wait_ms == 8500
        assert facts.cost_usd == pytest.approx(0.06)
        assert (facts.input_tokens, facts.output_tokens) == (30, 10)
        assert (facts.cache_read_tokens, facts.cache_write_tokens) == (7, None)
        assert facts.first_seen == at(0)
        assert facts.last_seen == at(4)
        assert facts.totals_partial is False

    def test_nothing_measured_reads_null(self) -> None:
        seed(self.team, [generation("t-1", 0, "s1"), generation("t-2", 2, "s1")])

        facts = self._facts("s1")["s1"]

        assert (facts.cost_usd, facts.input_tokens, facts.wait_ms) == (None, None, None)
        assert facts.duration_ms == 120_000

    def test_duration_runs_to_last_answer(self) -> None:
        seed(self.team, [root("t-1", 0, "s1", latency=30), root("t-2", 5, "s1", latency=120)])

        facts = self._facts("s1")["s1"]

        assert facts.duration_ms == 420_000
        assert facts.last_seen == at(5)

    def test_errored_turns_counts_flagged_traces(self) -> None:
        seed(
            self.team,
            [
                generation("t-bad", 0, "s1", props={"$ai_is_error": True}),
                generation("t-bad", 1, "s1", props={"$ai_is_error": True}),
                generation("t-worse", 2, "s1", props={"$ai_is_error": True}),
                generation("t-fine", 3, "s1"),
            ],
        )

        assert self._facts("s1")["s1"].errored_turns == 2

    def test_trace_naming_two_sessions_counts_in_both(self) -> None:
        seed(self.team, [generation("t-two", 0, "first"), generation("t-two", 1, "second")])

        facts = self._facts("first", "second")

        assert {key: value.turn_count for key, value in facts.items()} == {"first": 1, "second": 1}

    def test_duration_covers_an_untimed_trace_after_a_timed_one(self) -> None:
        seed(self.team, [root("t-timed", 0, "s1", latency=5), generation("t-untimed", 10, "s1")])

        assert self._facts("s1")["s1"].duration_ms == 600_000

    def test_support_traces_count_only_when_included_and_never_take_a_capped_place(self) -> None:
        seed(
            self.team,
            [
                generation("t-normal", 0, "s1"),
                generation("t-support", 1, "s1", props={"ai_support_impersonated": "true"}),
                generation("t-support-later", 2, "s1", props={"ai_support_impersonated": "true"}),
            ],
        )

        with patch.object(session_queries, "SESSION_FACTS_MAX_TRACES", 1):
            left_out = self._facts("s1")["s1"]
            included = self._facts("s1", include_support_traces=True)["s1"]

        assert (left_out.turn_count, left_out.first_seen, left_out.totals_partial) == (1, at(0), False)
        assert (included.turn_count, included.first_seen, included.totals_partial) == (1, at(2), True)

    def test_last_seen_includes_feedback_events(self) -> None:
        seed(self.team, [generation("t-1", 0, "s1"), event("$ai_feedback", "t-1", 7)])

        facts = self._facts("s1")["s1"]

        assert facts.last_seen == at(7)
        assert facts.first_seen == at(0)

    def test_a_session_past_the_trace_cap_counts_its_most_recent_traces_and_says_so(self) -> None:
        seed(
            self.team,
            [
                generation("t-oldest", 0, "busy", props={"$ai_total_cost_usd": 1}),
                generation("t-middle", 1, "busy", props={"$ai_total_cost_usd": 2}),
                generation("t-newest", 2, "busy", props={"$ai_total_cost_usd": 4}),
                generation("t-only", 3, "quiet"),
            ],
        )

        with patch.object(session_queries, "SESSION_FACTS_MAX_TRACES", 2):
            facts = self._facts("busy", "quiet")

        assert (facts["busy"].turn_count, facts["busy"].cost_usd, facts["busy"].totals_partial) == (2, 6, True)
        assert facts["busy"].first_seen == at(1)
        assert (facts["quiet"].turn_count, facts["quiet"].totals_partial) == (1, False)

    def test_an_event_without_a_trace_id_brings_no_untraced_events_into_its_session(self) -> None:
        seed(
            self.team,
            [
                generation("t-1", 0, "s1"),
                generation("", 1, "s1"),
                generation("", 2, props={"$ai_total_cost_usd": 9}),
            ],
        )

        facts = self._facts("s1")["s1"]

        assert (facts.turn_count, facts.cost_usd, facts.last_seen) == (1, None, at(0))

    def test_another_teams_session_never_counts(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other organization"))
        seed(other_team, [generation("t-foreign", 0, "s1")])
        seed(self.team, [generation("t-mine", 1, "s1")])

        assert self._facts("s1")["s1"].turn_count == 1

    def test_a_session_aged_out_of_ai_events_is_absent(self) -> None:
        self._seed_events_only([generation("t-old", 0, "s-old")])

        assert self._facts("s-old", "s-unknown") == {}

    def test_old_session_read_from_events_in_a_window(self) -> None:
        self._seed_events_only(
            [
                root("t-old", 0, latency=4),
                generation("t-old", 1, "s-old", props={"$ai_total_cost_usd": 0.5, "$ai_input_tokens": 12}),
                generation("t-old", 2, "s-old", props={"$ai_is_error": True}),
            ]
        )

        facts = self._shared_facts("s-old")["s-old"]

        assert facts.turn_count == 1
        assert facts.wait_ms == 4000
        assert facts.cost_usd == 0.5
        assert facts.input_tokens == 12
        assert facts.errored_turns == 1

    def test_old_session_counts_its_most_recent_traces_without_support_ones_and_says_when_capped(self) -> None:
        self._seed_events_only(
            [
                generation("t-1", 0, "s-old"),
                generation("t-2", 1, "s-old"),
                generation("t-support", 2, "s-old", props={"ai_support_impersonated": "true"}),
            ]
        )

        capped = self._shared_facts("s-old", max_traces=2)["s-old"]
        whole = self._shared_facts("s-old", max_traces=3)["s-old"]

        assert (capped.turn_count, capped.first_seen, capped.totals_partial) == (1, at(1), True)
        assert (whole.turn_count, whole.first_seen, whole.totals_partial) == (2, at(0), False)

    def _shared_facts(self, *session_ids: str, max_traces: int = 10) -> dict[str, SessionFacts]:
        return load_shared_session_facts(
            self.team, self.user, list(session_ids), window=fallback_window(at(0)), max_traces=max_traces
        )

    def _seed_events_only(self, events: list[dict[str, Any]]) -> None:
        bulk_create_events(
            [
                {
                    "event": item["event"],
                    "event_uuid": f"00000000-0000-4000-8000-{index:012d}",
                    "distinct_id": "distinct-1",
                    "team": self.team,
                    "timestamp": at(item["minutes"]),
                    "properties": {"$ai_trace_id": item["trace_id"], **item["properties"]},
                }
                for index, item in enumerate(events)
            ]
        )
