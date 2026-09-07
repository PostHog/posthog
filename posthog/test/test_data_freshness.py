from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.data_freshness import Freshness, ProjectFreshness, derive_freshness, reportable
from posthog.models.team.team import Team
from posthog.schema_enums import ProductKey

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
                {ProductKey.PRODUCT_ANALYTICS: _ago(0.1), ProductKey.SESSION_REPLAY: _ago(2)},
                Freshness.LIVE,
            ),
            (
                "one source silent while another keeps arriving is still in use",
                True,
                {ProductKey.PRODUCT_ANALYTICS: _ago(0.1), ProductKey.SESSION_REPLAY: _ago(11)},
                Freshness.LIVE,
            ),
            (
                "every source silent",
                True,
                {ProductKey.PRODUCT_ANALYTICS: _ago(9), ProductKey.LOGS: _ago(20)},
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
        found: dict[ProductKey, datetime],
        expected: Freshness,
    ) -> None:
        team = Team(id=1, ingested_event=ingested_event)

        result = derive_freshness(team, found, QUIET_BEFORE)

        self.assertEqual(result.freshness, expected)

    def test_reports_the_most_recent_source_first(self) -> None:
        team = Team(id=1, ingested_event=True)

        result = derive_freshness(
            team,
            {ProductKey.LOGS: _ago(5), ProductKey.SESSION_REPLAY: _ago(1), ProductKey.PRODUCT_ANALYTICS: _ago(3)},
            QUIET_BEFORE,
        )

        self.assertEqual(
            [source.data_source for source in result.sources],
            [ProductKey.SESSION_REPLAY, ProductKey.PRODUCT_ANALYTICS, ProductKey.LOGS],
        )
        self.assertEqual(result.last_data_at, _ago(1))

    def test_a_failed_probe_only_keeps_live_verdicts(self) -> None:
        # A probe that failed can't be told apart from a product with no data, so a stale or
        # never verdict might just be the missing probe. Warning on those would be wrong.
        results = [
            ProjectFreshness(team_id=1, freshness=Freshness.LIVE, last_data_at=_ago(0), sources=[]),
            ProjectFreshness(team_id=2, freshness=Freshness.STALE, last_data_at=_ago(20), sources=[]),
            ProjectFreshness(team_id=3, freshness=Freshness.NEVER, last_data_at=None, sources=[]),
        ]

        self.assertEqual(reportable(results, degraded=False), results)
        self.assertEqual([r.team_id for r in reportable(results, degraded=True)], [1])
