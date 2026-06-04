import pytest

from posthog.temporal.session_replay.session_summary.activities.video_based.a7b_emit_session_problem_signals import (
    filter_viewed_content_exceptions,
)
from posthog.temporal.session_replay.session_summary.types.video import (
    ConsolidatedVideoSegment,
    SessionProblem,
    classify_consolidated_segment_problem,
    collect_session_problems,
    is_posthog_viewer_surface_url,
    is_viewed_content_exception,
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


def _make_problem(**kwargs) -> SessionProblem:
    defaults = {
        "problem_type": "non_blocking_exception",
        "title": "Console error",
        "description": "Store creation failed: Product import is taking longer than expected",
        "start_time": "01:00",
        "end_time": "01:30",
    }
    defaults.update(kwargs)
    return SessionProblem(**defaults)


class TestIsPostHogViewerSurfaceUrl:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://us.posthog.com/project/367626/insights/abc#sessionRecordingId=019e9229", True),
            ("https://us.posthog.com/project/2/replay/home", True),
            ("https://us.posthog.com/project/2/replay", True),
            ("https://us.posthog.com/project/2/error_tracking/issue-id", True),
            ("https://us.posthog.com/project/2/logs", True),
            ("https://us.posthog.com/project/2/logs?query=x", True),
            ("https://us.posthog.com/project/2/insights/abc", False),
            ("https://us.posthog.com/project/2/dashboard/5", False),
            ("https://example.com/catalogs", False),
            ("https://example.com/blogs", False),
            ("https://customer.app/checkout", False),
            ("", False),
        ],
    )
    def test_detects_viewer_surfaces(self, url, expected):
        assert is_posthog_viewer_surface_url(url) is expected


class TestIsViewedContentException:
    @pytest.mark.parametrize(
        "problem_type, urls, expected",
        [
            # Exception fired only on viewer surfaces -> suppress
            ("non_blocking_exception", ["https://us.posthog.com/project/2/insights/a#sessionRecordingId=x"], True),
            ("blocking_exception", ["https://us.posthog.com/project/2/replay/home"], True),
            # Mixed: a real feature URL is present too -> do not suppress
            (
                "non_blocking_exception",
                ["https://us.posthog.com/project/2/replay/home", "https://customer.app/checkout"],
                False,
            ),
            # Non-exception problem types are never suppressed by URL
            ("confusion", ["https://us.posthog.com/project/2/replay/home"], False),
            ("abandonment", ["https://us.posthog.com/project/2/replay/home"], False),
            ("failure", ["https://us.posthog.com/project/2/replay/home"], False),
            # No URLs known -> cannot conclude viewed content, do not suppress
            ("non_blocking_exception", [], False),
            ("non_blocking_exception", [""], False),
            # Exception on a real feature surface -> keep
            ("non_blocking_exception", ["https://customer.app/checkout"], False),
        ],
    )
    def test_classifies_viewed_content(self, problem_type, urls, expected):
        assert is_viewed_content_exception(problem_type, urls) is expected


class TestFilterViewedContentExceptions:
    def test_empty_timeline_keeps_all(self):
        problems = [_make_problem()]
        kept, suppressed = filter_viewed_content_exceptions(problems, [])
        assert kept == problems
        assert suppressed == []

    def test_suppresses_exception_on_viewer_surface(self):
        problem = _make_problem(start_time="01:00", end_time="01:30")
        timeline = [(65.0, "https://us.posthog.com/project/2/insights/a#sessionRecordingId=x")]
        kept, suppressed = filter_viewed_content_exceptions([problem], timeline)
        assert kept == []
        assert suppressed == [problem]

    def test_keeps_exception_on_real_surface(self):
        problem = _make_problem(start_time="01:00", end_time="01:30")
        timeline = [(65.0, "https://customer.app/checkout")]
        kept, suppressed = filter_viewed_content_exceptions([problem], timeline)
        assert kept == [problem]
        assert suppressed == []

    def test_keeps_non_exception_problem_even_on_viewer_surface(self):
        problem = _make_problem(problem_type="confusion", start_time="01:00", end_time="01:30")
        timeline = [(65.0, "https://us.posthog.com/project/2/replay/home")]
        kept, suppressed = filter_viewed_content_exceptions([problem], timeline)
        assert kept == [problem]
        assert suppressed == []

    def test_keeps_problem_with_no_events_in_window(self):
        problem = _make_problem(start_time="01:00", end_time="01:30")
        # Event far outside the problem's window (plus margin) -> no URL context -> keep
        timeline = [(600.0, "https://us.posthog.com/project/2/replay/home")]
        kept, suppressed = filter_viewed_content_exceptions([problem], timeline)
        assert kept == [problem]
        assert suppressed == []

    def test_keeps_problem_with_unparseable_timestamp(self):
        problem = _make_problem(start_time="not-a-time", end_time="01:30")
        timeline = [(65.0, "https://us.posthog.com/project/2/replay/home")]
        kept, suppressed = filter_viewed_content_exceptions([problem], timeline)
        assert kept == [problem]
        assert suppressed == []
