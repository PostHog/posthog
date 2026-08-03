from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.data_freshness import DataSource, Freshness, derive_freshness
from posthog.models.team.team import Team

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
QUIET_BEFORE = NOW - timedelta(days=7)


def _ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


class TestDeriveFreshness(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "everything still arriving",
                True,
                {DataSource.PRODUCT_ANALYTICS: _ago(0.1), DataSource.SESSION_REPLAY: _ago(2)},
                Freshness.LIVE,
            ),
            (
                "one source silent while another keeps arriving is still in use",
                True,
                {DataSource.PRODUCT_ANALYTICS: _ago(0.1), DataSource.SESSION_REPLAY: _ago(11)},
                Freshness.LIVE,
            ),
            (
                "every source silent",
                True,
                {DataSource.PRODUCT_ANALYTICS: _ago(9), DataSource.LOGS: _ago(20)},
                Freshness.STALE,
            ),
            (
                "nothing in the window but the project has ingested before",
                True,
                {},
                Freshness.STALE,
            ),
            (
                "nothing in the window and the project never ingested",
                False,
                {},
                Freshness.NEVER,
            ),
        ]
    )
    def test_verdict(
        self,
        _name: str,
        ingested_event: bool,
        found: dict[DataSource, datetime],
        expected: Freshness,
    ) -> None:
        team = Team(id=1, ingested_event=ingested_event)

        result = derive_freshness(team, found, QUIET_BEFORE)

        self.assertEqual(result.freshness, expected)

    def test_reports_the_most_recent_source_first(self) -> None:
        team = Team(id=1, ingested_event=True)

        result = derive_freshness(
            team,
            {DataSource.LOGS: _ago(5), DataSource.SESSION_REPLAY: _ago(1), DataSource.PRODUCT_ANALYTICS: _ago(3)},
            QUIET_BEFORE,
        )

        self.assertEqual(
            [source.data_source for source in result.sources],
            [DataSource.SESSION_REPLAY, DataSource.PRODUCT_ANALYTICS, DataSource.LOGS],
        )
        self.assertEqual(result.last_data_at, _ago(1))
