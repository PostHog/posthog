import uuid
from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event

from django.utils import timezone

from posthog.models.ai_events.test_util import bulk_create_ai_events

from products.ai_observability.backend.eval_suggestions.measure import (
    EVENTS_PER_TRACE,
    MAX_OUTPUT_BYTES,
    _sampled_trace,
    fetch_sample,
)
from products.ai_observability.backend.eval_suggestions.profile import ProfileWindow, fetch_profile


class TestSample(ClickhouseTestMixin, APIBaseTest):
    def _generation(
        self,
        trace_id: str,
        at: datetime,
        answer: str = "Here is the summary.",
        *,
        messages: list[dict[str, str]] | None = None,
        properties: dict[str, str] | None = None,
        copies: int = 1,
    ) -> None:
        event_uuid = str(uuid.uuid4())
        light = {"$ai_trace_id": trace_id, "$ai_model": "example-model-mini", **(properties or {})}
        _create_event(
            team=self.team,
            event="$ai_generation",
            distinct_id="user-1",
            timestamp=at,
            properties=light,
            event_uuid=event_uuid,
        )
        bulk_create_ai_events(
            [
                {
                    "event": "$ai_generation",
                    "event_uuid": event_uuid,
                    "distinct_id": "user-1",
                    "team_id": self.team.pk,
                    "timestamp": at,
                    "properties": {
                        **light,
                        "$ai_input": messages or [{"role": "user", "content": "Summarize my notes"}],
                        "$ai_output_choices": [{"role": "assistant", "content": answer}],
                    },
                }
            ]
            * copies
        )

    def test_a_trace_across_the_held_out_boundary_is_sampled_once(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        self._generation("older", end - timedelta(days=3))
        self._generation("across", end - timedelta(days=1, hours=1))
        self._generation("across", end - timedelta(hours=2))
        self._generation("recent", end - timedelta(hours=3))
        window = ProfileWindow(start=end - timedelta(days=7), end=end)

        sample = fetch_sample(self.team, window, fetch_profile(self.team, window))

        assert sorted(s.trace.id for s in sample.main) == ["across", "older"]
        assert [s.trace.id for s in sample.held_out] == ["recent"]

    def test_a_trace_whose_final_answer_is_too_long_to_read_is_not_sampled(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        self._generation("short", end - timedelta(hours=5))
        self._generation("long", end - timedelta(hours=4))
        self._generation("long", end - timedelta(hours=3), answer="x" * (MAX_OUTPUT_BYTES + 1))
        window = ProfileWindow(start=end - timedelta(days=7), end=end)

        sample = fetch_sample(self.team, window, fetch_profile(self.team, window))

        assert [s.trace.id for s in sample.traces] == ["short"]

    def test_hydration_reads_each_event_once_and_skips_traces_past_the_cap(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        # Ingestion can write one event twice. Counted twice, it would double tokens and use up the cap.
        self._generation("duplicated", end - timedelta(hours=5), copies=2)
        for index in range(EVENTS_PER_TRACE + 1):
            self._generation("too_long", end - timedelta(hours=4, seconds=index))
        window = ProfileWindow(start=end - timedelta(days=7), end=end)

        sample = fetch_sample(self.team, window, fetch_profile(self.team, window))

        assert [(s.trace.id, len(s.trace.events)) for s in sample.traces] == [("duplicated", 1)]

    def test_a_trace_keeps_the_reply_the_user_answered(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        history = [
            {"role": "user", "content": "Archive my notes"},
            {"role": "assistant", "content": "I archived all 40 notes."},
            {"role": "user", "content": "No, only the ones from March."},
        ]
        self._generation("turn", end - timedelta(hours=3), messages=history)
        window = ProfileWindow(start=end - timedelta(days=7), end=end)

        sampled = fetch_sample(self.team, window, fetch_profile(self.team, window)).traces[0]

        reply, correction = sampled.turn_text.find("I archived all 40 notes."), sampled.turn_text.find("only the ones")
        assert 0 <= reply < correction


def test_a_trace_holds_the_segment_value_of_every_generation() -> None:
    at = datetime(2026, 11, 1, tzinfo=UTC)
    rows = [
        (
            "t",
            f"e{index}",
            "$ai_generation",
            at + timedelta(seconds=index),
            "u",
            {"ai_product": product},
            "",
            1,
            False,
            "",
            "",
            False,
            "",
        )
        for index, product in enumerate(["chat-1", "search"])
    ]

    sampled = _sampled_trace("t", rows, held_out=False, spans_days=False, segment_keys=["ai_product"])

    assert sampled is not None
    assert sampled.segments == {"ai_product": "search"}
    assert sampled.segment_values == {"ai_product": frozenset({"chat", "search"})}
