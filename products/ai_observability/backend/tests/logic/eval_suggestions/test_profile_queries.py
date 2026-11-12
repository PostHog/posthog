from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event

from django.utils import timezone

from products.ai_observability.backend.logic.eval_suggestions.profile_queries import (
    ErrorPrefixRow,
    ProfileWindow,
    SegmentValueRow,
    ToolCallsRow,
    TrafficCounts,
    load_daily_traffic,
    load_error_prefixes,
    load_segment_values,
    load_tool_calls,
    load_traffic_counts,
)


class TestProfileQueries(ClickhouseTestMixin, BaseTest):
    def _generation(self, trace_id: str, hours_ago: float, properties: dict[str, Any]) -> None:
        _create_event(
            team=self.team,
            event="$ai_generation",
            distinct_id="user-1",
            timestamp=self.end - timedelta(hours=hours_ago),
            properties={"$ai_trace_id": trace_id, "$ai_model": "example-model-mini", **properties},
        )

    def test_the_profile_reads_traffic_tools_errors_and_segments(self) -> None:
        self.end = timezone.now() - timedelta(minutes=30)
        for index, product in enumerate(["chat-1", "chat-2", "search"]):
            self._generation(
                f"trace-{index}",
                3 + index / 60,
                {"ai_product": product, "$ai_tools_called": "search, fetch", "$ai_session_id": "s1"},
            )
        self._generation(
            "failed", 48, {"ai_product": "search", "$ai_is_error": True, "$ai_error": "RateLimitError: slow down"}
        )
        window = ProfileWindow(start=self.end - timedelta(days=7), end=self.end)

        assert load_traffic_counts(self.team, window) == TrafficCounts(generations=4, sessions=1, session_traces=3)
        daily = sorted(load_daily_traffic(self.team, window, 1000), key=lambda row: row.days_ago)
        assert [(r.days_ago, r.generations, r.traces, r.with_tools, r.with_session) for r in daily] == [
            (0, 3, 3, 3, 3),
            (2, 1, 1, 0, 0),
        ]
        assert daily[0].models == ("example-model-mini",)
        assert sorted(load_tool_calls(self.team, window, 1000), key=lambda row: row.tool) == [
            ToolCallsRow(tool="fetch", calls=3),
            ToolCallsRow(tool="search", calls=3),
        ]
        assert load_error_prefixes(self.team, window) == [ErrorPrefixRow(prefix="RateLimitError: slow down", errors=1)]
        assert sorted(load_segment_values(self.team, window, 1000), key=lambda row: row.value) == [
            SegmentValueRow(key="ai_product", value="chat", generations=2),
            SegmentValueRow(key="ai_product", value="search", generations=2),
        ]
