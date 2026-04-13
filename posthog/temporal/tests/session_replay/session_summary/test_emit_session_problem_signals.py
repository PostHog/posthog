import datetime

import pytest

from posthog.temporal.session_replay.session_summary.activities.a6a_emit_session_problem_signals import (
    _build_segment_event_history,
)
from posthog.temporal.session_replay.session_summary.utils import format_seconds_as_mm_ss, parse_str_timestamp_to_s

UTC = datetime.UTC


class TestParseTimeToSeconds:
    @pytest.mark.parametrize(
        "time_str, expected",
        [
            ("00:00", 0),
            ("00:30", 30),
            ("02:15", 135),
            ("10:00", 600),
            ("59:59", 3599),
            ("1:00:00", 3600),
            ("1:30:00", 5400),
            ("2:05:30", 7530),
        ],
    )
    def test_parses_correctly(self, time_str, expected):
        assert parse_str_timestamp_to_s(time_str) == expected

    def test_rejects_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid timestamp format"):
            parse_str_timestamp_to_s("bad")


class TestFormatSecondsAsTime:
    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (0, "00:00.000"),
            (30, "00:30.000"),
            (30.456, "00:30.456"),
            (135, "02:15.000"),
            (135.1, "02:15.100"),
            (3599.999, "59:59.999"),
            (3600, "1:00:00.000"),
            (5400, "1:30:00.000"),
        ],
    )
    def test_formats_correctly(self, seconds, expected):
        assert format_seconds_as_mm_ss(seconds, include_ms=True) == expected


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

    def test_handles_string_timestamps(self):
        events: list[tuple[str, str, str, list[str], list[str], str, str, str]] = [
            (
                "$pageview",
                "2025-01-01T00:00:45+00:00",
                "",
                [],
                [],
                "w1",
                "https://example.com",
                "",
            )
        ]
        result = _build_segment_event_history(events, COLUMNS, SESSION_START, 30, 60)
        assert len(result) == 1
        assert result[0]["timestamp"] == "00:45.000"
