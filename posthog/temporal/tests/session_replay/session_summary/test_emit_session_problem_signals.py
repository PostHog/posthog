import pytest

from posthog.temporal.session_replay.session_summary.types.video import (
    ConsolidatedVideoSegment,
    classify_consolidated_segment_problem,
    collect_session_problems,
)


def _make_segment(**kwargs) -> ConsolidatedVideoSegment:
    defaults = {
        "title": "Test segment",
        "start_time": "00:00",
        "end_time": "01:00",
        "description": "Test",
        "success": True,
        "exception": None,
        "confusion_detected": False,
        "abandonment_detected": False,
    }
    defaults.update(kwargs)
    return ConsolidatedVideoSegment(**defaults)


class TestClassifyProblem:
    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            ({"exception": "blocking"}, "blocking_exception"),
            ({"abandonment_detected": True}, "abandonment"),
            ({"exception": "non-blocking"}, "non_blocking_exception"),
            ({"confusion_detected": True}, "confusion"),
            ({"success": False}, "failure"),
            ({}, None),
        ],
        ids=["blocking", "abandonment", "non_blocking", "confusion", "failure", "no_problem"],
    )
    def test_single_flag(self, kwargs, expected):
        assert classify_consolidated_segment_problem(_make_segment(**kwargs)) == expected

    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            (
                {"exception": "blocking", "abandonment_detected": True, "confusion_detected": True, "success": False},
                "blocking_exception",
            ),
            (
                {
                    "abandonment_detected": True,
                    "exception": "non-blocking",
                    "confusion_detected": True,
                    "success": False,
                },
                "abandonment",
            ),
            ({"exception": "non-blocking", "confusion_detected": True, "success": False}, "non_blocking_exception"),
            ({"confusion_detected": True, "success": False}, "confusion"),
        ],
        ids=["blocking_wins_all", "abandonment_wins_lower", "non_blocking_wins_lower", "confusion_wins_failure"],
    )
    def test_priority_ordering(self, kwargs, expected):
        assert classify_consolidated_segment_problem(_make_segment(**kwargs)) == expected


class TestCollectSessionProblems:
    def test_returns_empty_when_no_problematic_segments(self):
        segments = [_make_segment(), _make_segment(title="Another fine segment")]
        assert collect_session_problems(segments) == []

    def test_filters_out_non_problem_segments_and_preserves_order(self):
        segments = [
            _make_segment(title="Healthy"),
            _make_segment(
                title="Blocking error",
                description="Boom",
                start_time="00:10",
                end_time="00:20",
                exception="blocking",
            ),
            _make_segment(title="Still healthy"),
            _make_segment(
                title="Abandoned flow",
                description="User gave up",
                start_time="00:30",
                end_time="00:40",
                abandonment_detected=True,
            ),
        ]
        problems = collect_session_problems(segments)
        assert [p.problem_type for p in problems] == ["blocking_exception", "abandonment"]
        assert [p.title for p in problems] == ["Blocking error", "Abandoned flow"]
        assert [p.start_time for p in problems] == ["00:10", "00:30"]
        assert [p.end_time for p in problems] == ["00:20", "00:40"]
        assert [p.description for p in problems] == ["Boom", "User gave up"]

    def test_uses_most_severe_problem_type_when_multiple_flags_set(self):
        segments = [
            _make_segment(
                title="Multi-problem",
                description="...",
                start_time="00:00",
                end_time="00:05",
                exception="non-blocking",
                confusion_detected=True,
                success=False,
            ),
        ]
        problems = collect_session_problems(segments)
        assert len(problems) == 1
        assert problems[0].problem_type == "non_blocking_exception"
