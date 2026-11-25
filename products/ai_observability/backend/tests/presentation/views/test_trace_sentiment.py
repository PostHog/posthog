from datetime import timedelta

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from .trace_fixtures import PAGE_BOUNDS, T0, TraceEvents, post_page_read


@time_machine.travel(T0 + timedelta(days=1), tick=False)
class TestTraceSentimentViewSet(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand([("browser session", None), ("read key", ["llm_analytics:read"])])
    def test_reads_the_sentiment_of_each_trace_on_a_page(self, _name: str, scopes: list[str] | None) -> None:
        events = TraceEvents(self.team)
        events.add("trace-1")
        events.add(
            "trace-1",
            event="$ai_evaluation",
            properties={
                "$ai_evaluation_runtime": "sentiment",
                "$ai_target_event_id": "generation-1",
                "$ai_sentiment_label": "positive",
                "$ai_sentiment_score": 0.9,
                "$ai_sentiment_scores": {"positive": 0.9, "neutral": 0.08, "negative": 0.02},
                "$ai_sentiment_message_count": 1,
            },
        )
        events.seed()

        response = post_page_read(self, "sentiment", {"trace_ids": ["trace-1"], **PAGE_BOUNDS}, scopes=scopes)

        assert (response.status_code, response.json()) == (
            200,
            {"items": [{"traceId": "trace-1", "sentiment": {"label": "positive", "score": 0.9}}]},
        )
