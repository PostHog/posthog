import datetime

import pytest

from posthog.temporal.session_replay.session_summary.activities.a6a_emit_session_problem_signals import (
    _build_segment_event_history,
    _classify_problem,
)
from posthog.temporal.session_replay.session_summary.types.video import ConsolidatedVideoSegment

UTC = datetime.UTC


COLUMNS = [
    "event",
    "timestamp",
    "elements_chain_href",
    "elements_chain_texts",
    "elements_chain_elements",
    "$window_id",
    "$current_url",
    "$event_type",
]
SESSION_START = datetime.datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)


def _make_event(
    event: str,
    offset_seconds: float,
    current_url: str = "",
    event_type: str = "",
    texts: list[str] | None = None,
) -> tuple:
    return (
        event,
        SESSION_START + datetime.timedelta(seconds=offset_seconds),
        "",  # elements_chain_href
        texts or [],
        [],  # elements_chain_elements
        "w1",  # $window_id
        current_url,
        event_type,
    )


class TestBuildSegmentEventHistory:
    def test_filters_events_to_segment_time_range(self):
        events = [
            _make_event("$pageview", 10, "https://example.com/before"),
            _make_event("$pageview", 35, "https://example.com/in-range"),
            _make_event("$autocapture", 50, "https://example.com/in-range", "click", ["Submit"]),
            _make_event("$pageview", 200, "https://example.com/after"),
        ]
        result = _build_segment_event_history(events, COLUMNS, SESSION_START, 30, 60)
        assert len(result) == 2
        assert result[0]["event"] == "$pageview"
        assert result[0]["current_url"] == "https://example.com/in-range"
        assert result[1]["event"] == "$autocapture"
        assert result[1]["event_type"] == "click"
        assert result[1]["interaction_text"] == "Submit"

    def test_timestamps_are_relative_to_session_start_with_millis(self):
        events = [_make_event("$pageview", 90.123, "https://example.com")]
        result = _build_segment_event_history(events, COLUMNS, SESSION_START, 60, 120)
        assert result[0]["timestamp"] == "01:30.123"

    def test_omits_empty_optional_fields(self):
        events = [_make_event("$pageview", 30)]
        result = _build_segment_event_history(events, COLUMNS, SESSION_START, 0, 60)
        assert len(result) == 1
        assert "current_url" not in result[0]
        assert "event_type" not in result[0]
        assert "interaction_text" not in result[0]

    def test_joins_multiple_chain_texts(self):
        events = [_make_event("$autocapture", 30, texts=["Add to cart", "Buy now"])]
        result = _build_segment_event_history(events, COLUMNS, SESSION_START, 0, 60)
        assert result[0]["interaction_text"] == "Add to cart > Buy now"

    def test_returns_empty_list_for_no_matching_events(self):
        events = [_make_event("$pageview", 200)]
        result = _build_segment_event_history(events, COLUMNS, SESSION_START, 0, 60)
        assert result == []

    def test_caps_at_max_events(self):
        events = [_make_event("$autocapture", i) for i in range(100)]
        result = _build_segment_event_history(events, COLUMNS, SESSION_START, 0, 200)
        assert len(result) == 50  # MAX_EVENTS_PER_SEGMENT

    def test_parses_iso_string_timestamps(self):
        events: list[tuple] = [
            ("$pageview", "2025-01-01T00:00:45+00:00", "", [], [], "w1", "https://example.com", ""),
        ]
        result = _build_segment_event_history(events, COLUMNS, SESSION_START, 30, 60)
        assert len(result) == 1
        assert result[0]["timestamp"] == "00:45.000"

    def test_skips_non_datetime_non_string_timestamps(self):
        """clickhouse_driver returns datetime objects, but ints/None are defensively skipped."""
        events: list[tuple] = [
            ("$pageview", 1735689645, "", [], [], "w1", "https://example.com", ""),
            ("$pageview", None, "", [], [], "w1", "https://example.com", ""),
        ]
        result = _build_segment_event_history(events, COLUMNS, SESSION_START, 0, 3600)
        assert result == []

    def test_returns_empty_when_required_columns_missing(self):
        events = [_make_event("$pageview", 30)]
        assert _build_segment_event_history(events, ["event", "$current_url"], SESSION_START, 0, 60) == []
        assert _build_segment_event_history(events, ["timestamp", "$current_url"], SESSION_START, 0, 60) == []
        assert _build_segment_event_history(events, ["$current_url"], SESSION_START, 0, 60) == []

    def test_includes_events_at_exact_segment_boundaries(self):
        events = [
            _make_event("$pageview", 30, "https://example.com/at-start"),
            _make_event("$autocapture", 60, "https://example.com/at-end"),
        ]
        result = _build_segment_event_history(events, COLUMNS, SESSION_START, 30, 60)
        assert len(result) == 2
        assert result[0]["current_url"] == "https://example.com/at-start"
        assert result[1]["current_url"] == "https://example.com/at-end"

    def test_omits_optional_fields_when_columns_absent(self):
        minimal_columns = ["event", "timestamp"]
        events = [("$pageview", SESSION_START + datetime.timedelta(seconds=30))]
        result = _build_segment_event_history(events, minimal_columns, SESSION_START, 0, 60)
        assert result == [{"event": "$pageview", "timestamp": "00:30.000"}]

    def test_skips_all_empty_chain_texts(self):
        events = [_make_event("$autocapture", 30, texts=["", ""])]
        result = _build_segment_event_history(events, COLUMNS, SESSION_START, 0, 60)
        assert len(result) == 1
        assert "interaction_text" not in result[0]


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
