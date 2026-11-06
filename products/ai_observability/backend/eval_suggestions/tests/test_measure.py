import uuid
from datetime import datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event

from django.utils import timezone

from posthog.models.ai_events.test_util import bulk_create_ai_events

from products.ai_observability.backend.eval_suggestions.measure import MAX_OUTPUT_BYTES, fetch_sample
from products.ai_observability.backend.eval_suggestions.profile import ProfileWindow, fetch_profile


class TestSample(ClickhouseTestMixin, APIBaseTest):
    def _generation(self, trace_id: str, at: datetime, answer: str = "Here is the summary.") -> None:
        event_uuid = str(uuid.uuid4())
        light = {"$ai_trace_id": trace_id, "$ai_model": "example-model-mini"}
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
                        "$ai_input": [{"role": "user", "content": "Summarize my notes"}],
                        "$ai_output_choices": [{"role": "assistant", "content": answer}],
                    },
                }
            ]
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
