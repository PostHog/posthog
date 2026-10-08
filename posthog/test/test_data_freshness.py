from datetime import UTC, datetime, timedelta
from typing import Optional

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.data_freshness import (
    LOOKBACK_DAYS,
    DataSourceSpec,
    Freshness,
    ProjectFreshness,
    SourceFreshness,
    _compute,
    derive_freshness,
    reportable,
)
from posthog.models.team.team import Team
from posthog.schema_enums import ProductKey

from products.event_definitions.backend.models.event_definition import EventDefinition
from products.feature_flags.backend.data_freshness import DATA_SOURCES as FEATURE_FLAGS_DATA_SOURCES
from products.feature_flags.backend.models.feature_flag import FeatureFlag

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


class TestFeatureFlagsFreshness(BaseTest):
    other_team: Team
    other_team_called_at: datetime

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.other_team = Team.objects.create(organization=cls.organization)
        cls.other_team_called_at = datetime.now(UTC) - timedelta(minutes=5)
        FeatureFlag.objects.create(
            team=cls.other_team, key="busy-flag", created_by=cls.user, last_called_at=cls.other_team_called_at
        )

    def setUp(self) -> None:
        super().setUp()
        # Production also runs the product analytics residual. It takes `$feature_flag_called`
        # when the flags spec stops claiming the event.
        residual = DataSourceSpec(product=ProductKey.PRODUCT_ANALYTICS, is_residual=True)
        patcher = patch(
            "posthog.data_freshness.discover_data_sources",
            return_value=(*FEATURE_FLAGS_DATA_SOURCES, residual),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @parameterized.expand(
        [
            (
                "latest call across flags without an event definition",
                [None, timedelta(days=3), timedelta(hours=1)],
                False,
                None,
                timedelta(hours=1),
            ),
            ("soft-deleted flag still called", [timedelta(hours=1)], True, None, timedelta(hours=1)),
            ("event definition for a key with no flag", [], False, timedelta(hours=2), timedelta(hours=2)),
            (
                "event definition newer than the latest flag call",
                [timedelta(days=3)],
                False,
                timedelta(hours=2),
                timedelta(hours=2),
            ),
            (
                "flag call newer than the event definition",
                [timedelta(hours=1)],
                False,
                timedelta(hours=2),
                timedelta(hours=1),
            ),
            ("last call before the lookback window", [timedelta(days=LOOKBACK_DAYS + 1)], False, None, None),
        ]
    )
    def test_flag_calls(
        self,
        _name: str,
        called_ago: list[Optional[timedelta]],
        deleted: bool,
        event_definition_ago: Optional[timedelta],
        expected_ago: Optional[timedelta],
    ) -> None:
        now = datetime.now(UTC)
        for index, ago in enumerate(called_ago):
            FeatureFlag.objects.create(
                team=self.team,
                key=f"flag-{index}",
                created_by=self.user,
                last_called_at=None if ago is None else now - ago,
                deleted=deleted,
            )
        if event_definition_ago is not None:
            EventDefinition.objects.create(
                team=self.team, name="$feature_flag_called", last_seen_at=now - event_definition_ago
            )

        results = {result.team_id: result for result in _compute([self.team, self.other_team])}

        expected_sources = (
            [SourceFreshness(data_source=ProductKey.FEATURE_FLAGS, last_data_at=now - expected_ago)]
            if expected_ago is not None
            else []
        )
        self.assertEqual(results[self.team.id].sources, expected_sources)
        self.assertEqual(results[self.other_team.id].last_data_at, self.other_team_called_at)
