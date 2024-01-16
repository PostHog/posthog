from datetime import timezone, datetime

from dateutil.parser import isoparse

from posthog.session_recordings.session_summary.summarize_session import (
    format_dates,
    simplify_window_id,
    deduplicate_urls,
    collapse_sequence_of_events,
)
from posthog.test.base import BaseTest


class TestSummarizeSessions(BaseTest):
    def test_format_dates_as_millis_since_start(self) -> None:
        columns, results = format_dates(
            (
                ["event", "timestamp"],
                [
                    ["$pageview", isoparse("2021-01-01T00:00:00Z")],
                    ["$pageview", isoparse("2021-01-01T00:00:01Z")],
                    ["$pageview", isoparse("2021-01-01T00:00:02Z")],
                ],
            ),
            datetime(2021, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        assert columns == ["event", "milliseconds_since_start"]
        assert results == [("$pageview", 0), ("$pageview", 1000), ("$pageview", 2000)]

    def test_simplify_window_id(self) -> None:
        columns, results = simplify_window_id(
            (
                ["event", "timestamp", "$window_id"],
                [
                    ["$pageview-1-1", isoparse("2021-01-01T00:00:00Z"), "window-the-first"],
                    ["$pageview-1-2", isoparse("2021-01-01T00:00:01Z"), "window-the-first"],
                    ["$pageview-2-1", isoparse("2021-01-01T00:00:02Z"), "window-the-second"],
                    ["$pageview-4-1", isoparse("2021-01-01T00:00:02Z"), "window-the-fourth"],
                    ["$pageview-3-1", isoparse("2021-01-01T00:00:02Z"), "window-the-third"],
                    ["$pageview-1-3", isoparse("2021-01-01T00:00:02Z"), "window-the-first"],
                ],
            )
        )

        assert columns == ["event", "timestamp", "$window_id"]
        assert results == [
            ("$pageview-1-1", isoparse("2021-01-01T00:00:00Z"), 1),
            ("$pageview-1-2", isoparse("2021-01-01T00:00:01Z"), 1),
            ("$pageview-2-1", isoparse("2021-01-01T00:00:02Z"), 2),
            # window the fourth has index 3...
            # in reality these are mapping from UUIDs
            # and this apparent switch of number wouldn't stand out
            ("$pageview-4-1", isoparse("2021-01-01T00:00:02Z"), 3),
            ("$pageview-3-1", isoparse("2021-01-01T00:00:02Z"), 4),
            ("$pageview-1-3", isoparse("2021-01-01T00:00:02Z"), 1),
        ]

    def test_collape_sequence_of_events(self) -> None:
        columns, results = collapse_sequence_of_events(
            (
                ["event", "timestamp", "$window_id"],
                [
                    # these collapse because they're a sequence
                    ["$pageview", isoparse("2021-01-01T00:00:00Z"), 1],
                    ["$pageview", isoparse("2021-01-01T01:00:00Z"), 1],
                    ["$pageview", isoparse("2021-01-01T02:00:00Z"), 1],
                    ["$pageview", isoparse("2021-01-01T03:00:00Z"), 1],
                    # these don't collapse because they're different windows
                    ["$autocapture", isoparse("2021-01-01T00:00:00Z"), 1],
                    ["$autocapture", isoparse("2021-01-01T01:00:00Z"), 2],
                    # these don't collapse because they're not a sequence
                    ["$a", isoparse("2021-01-01T01:00:00Z"), 2],
                    ["$b", isoparse("2021-01-01T01:00:00Z"), 2],
                    ["$c", isoparse("2021-01-01T01:00:00Z"), 2],
                ],
            )
        )
        assert columns == ["event", "timestamp", "$window_id", "event_repetition_count"]
        assert results == [
            ("$pageview", isoparse("2021-01-01T00:00:00Z"), 1, 4),
            ("$autocapture", isoparse("2021-01-01T00:00:00Z"), 1, None),
            ("$autocapture", isoparse("2021-01-01T01:00:00Z"), 2, None),
            ("$a", isoparse("2021-01-01T01:00:00Z"), 2, None),
            ("$b", isoparse("2021-01-01T01:00:00Z"), 2, None),
            ("$c", isoparse("2021-01-01T01:00:00Z"), 2, None),
        ]

    def test_deduplicate_ids(self) -> None:
        columns, results, url_mapping = deduplicate_urls(
            (
                ["event", "$current_url"],
                [
                    ["$pageview-one", "https://example.com/one"],
                    ["$pageview-two", "https://example.com/two"],
                    ["$pageview-one", "https://example.com/one"],
                    ["$pageview-one", "https://example.com/one"],
                    ["$pageview-two", "https://example.com/two"],
                    ["$pageview-three", "https://example.com/three"],
                ],
            )
        )
        assert columns == ["event", "$current_url"]
        assert results == [
            ("$pageview-one", "url_1"),
            ("$pageview-two", "url_2"),
            ("$pageview-one", "url_1"),
            ("$pageview-one", "url_1"),
            ("$pageview-two", "url_2"),
            ("$pageview-three", "url_3"),
        ]
        assert url_mapping == {
            "https://example.com/one": "url_1",
            "https://example.com/two": "url_2",
            "https://example.com/three": "url_3",
        }
