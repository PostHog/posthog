from datetime import timezone, datetime

from dateutil.parser import isoparse

from posthog.session_recordings.session_summary.summarize_session import format_dates
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
