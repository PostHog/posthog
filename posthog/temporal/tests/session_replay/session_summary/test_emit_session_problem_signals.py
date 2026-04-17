import pytest

from posthog.temporal.session_replay.session_summary.activities.a6a_emit_session_problem_signals import (
    _classify_problem,
)
from posthog.temporal.session_replay.session_summary.types.video import ConsolidatedVideoSegment


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
        assert _classify_problem(_make_segment(**kwargs)) == expected

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
        assert _classify_problem(_make_segment(**kwargs)) == expected
