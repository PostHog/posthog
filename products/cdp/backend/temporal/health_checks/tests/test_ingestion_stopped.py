from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.models import Team

from products.cdp.backend.temporal.health_checks.ingestion_stopped import IngestionStoppedCheck


class TestIngestionStoppedCheck(ClickhouseTestMixin, BaseTest):
    def _send_hourly(self, team: Team, hours_ago: range) -> None:
        now = datetime.now(UTC)
        for hours in hours_ago:
            _create_event(team=team, event="$pageview", distinct_id="user", timestamp=now - timedelta(hours=hours))

    @parameterized.expand(
        [
            ("steady_then_silent", range(4, 27), True),
            ("steady_and_still_sending", range(0, 27), False),
            ("sparse_then_silent", range(4, 14), False),
        ]
    )
    def test_detect(self, _name: str, hours_ago: range, expect_issue: bool) -> None:
        self._send_hourly(self.team, hours_ago)
        flush_persons_and_events()

        issues = IngestionStoppedCheck().detect([self.team.pk])

        self.assertEqual(self.team.pk in issues, expect_issue)
