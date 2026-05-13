from unittest.mock import patch

from parameterized import parameterized

from posthog.temporal.mcp_analytics.labeling import _heuristic_gap_score, label_cluster
from posthog.temporal.mcp_analytics.models import IntentStat


def _stat(
    intent: str,
    total: int = 10,
    errors: int = 0,
    empty: int = 0,
    distinct_tools: int = 1,
    dominant_tool: str = "noop",
) -> IntentStat:
    return IntentStat(
        intent=intent,
        total_calls=total,
        error_count=errors,
        empty_response_count=empty,
        distinct_tools_attempted=distinct_tools,
        dominant_tool=dominant_tool,
    )


class TestHeuristicGapScore:
    @parameterized.expand(
        [
            # (case_label, samples, min_inclusive, max_exclusive)
            ("empty_samples", [], 0.0, 0.0001),
            (
                "low_signal_low_score",
                [_stat("query", total=10, errors=0, empty=0, distinct_tools=1)],
                0.0,
                0.1,
            ),
            (
                "high_failure_high_score",
                [_stat("export dashboard as pdf", total=10, errors=10, empty=0, distinct_tools=5)],
                0.5,
                1.01,
            ),
            (
                "empty_responses_contribute",
                # 0.3 * 1.0 (empty rate) + 0.3 * min(2/5, 1) = 0.3 + 0.12 = 0.42
                [_stat("send slack message", total=10, errors=0, empty=10, distinct_tools=2)],
                0.4,
                0.5,
            ),
        ]
    )
    def test_heuristic_gap_score_range(
        self, _name: str, samples: list[IntentStat], min_inclusive: float, max_exclusive: float
    ) -> None:
        score = _heuristic_gap_score(samples)
        assert min_inclusive <= score < max_exclusive, f"{score} not in [{min_inclusive}, {max_exclusive})"


class TestLabelClusterFallback:
    def test_label_cluster_falls_back_when_llm_fails(self) -> None:
        samples = [
            _stat("export dashboard as pdf", total=10, errors=8, empty=0, distinct_tools=4),
            _stat("download dashboard pdf", total=4, errors=4, empty=0, distinct_tools=3),
        ]
        with patch(
            "posthog.temporal.mcp_analytics.labeling.Client.complete",
            side_effect=RuntimeError("boom"),
        ):
            label = label_cluster(samples)

        assert "export" in label.title.lower()
        assert label.gap_score > 0.0
        assert "fallback" in label.description.lower()

    def test_label_cluster_empty_samples(self) -> None:
        label = label_cluster([])
        assert label.title == "Empty cluster"
        assert label.gap_score == 0.0
