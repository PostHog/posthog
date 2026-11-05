import uuid
from datetime import datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils import timezone

from products.ai_observability.backend.eval_suggestions.demo import DemoEvent, insert_demo_events
from products.ai_observability.backend.eval_suggestions.measure import fetch_sample
from products.ai_observability.backend.eval_suggestions.profile import ProfileWindow, fetch_profile


def _generation(trace_id: str, before_end: timedelta, end: datetime) -> DemoEvent:
    return DemoEvent(
        event="$ai_generation",
        uuid=str(uuid.uuid4()),
        distinct_id="user-1",
        timestamp=end - before_end,
        properties={
            "$ai_trace_id": trace_id,
            "$ai_model": "example-model-mini",
            "$ai_input": [{"role": "user", "content": "Summarize my notes"}],
            "$ai_output_choices": [{"role": "assistant", "content": "Here is the summary."}],
        },
    )


class TestSample(ClickhouseTestMixin, APIBaseTest):
    def test_a_trace_across_the_held_out_boundary_is_sampled_once(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        insert_demo_events(
            self.team.pk,
            [
                _generation("older", timedelta(days=3), end),
                _generation("across", timedelta(days=1, hours=1), end),
                _generation("across", timedelta(hours=2), end),
                _generation("recent", timedelta(hours=3), end),
            ],
        )
        window = ProfileWindow(start=end - timedelta(days=7), end=end)

        sample = fetch_sample(self.team, window, fetch_profile(self.team, window))

        assert sorted(s.trace.id for s in sample.main) == ["across", "older"]
        assert [s.trace.id for s in sample.held_out] == ["recent"]
