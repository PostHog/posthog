from datetime import date, timedelta
from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.cost.statistics import (
    EVENT_VOLUME_WINDOW_DAYS,
    ClickHouseStatisticsProvider,
    EventVolume,
    FixedStatisticsProvider,
)

from posthog.clickhouse.client import sync_execute
from posthog.models.usage_report_events_preagg.sql import (
    DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
    SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
    WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE,
    WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
)

# Seeded rows must sit inside the rollup's 14-day TTL or ClickHouse drops the part on its next merge, so the
# fixtures are relative to the real clock and the provider is handed the same day.
TODAY = date.today()


class TestEventVolume(SimpleTestCase):
    def test_per_day_and_event_fraction_scale_from_the_recorded_window(self):
        volume = EventVolume(total=1_000, by_event={"$pageview": 600, "signup": 400}, days=10)

        assert volume.per_day == 100.0
        assert volume.event_fraction("$pageview") == 0.6
        assert volume.event_fraction("never_seen") is None

    def test_empty_volume_does_not_divide_by_zero(self):
        volume = EventVolume(total=0, by_event={}, days=0)

        assert volume.per_day == 0.0
        assert volume.event_fraction("$pageview") is None

    def test_fixed_provider_returns_none_for_unknown_teams(self):
        provider = FixedStatisticsProvider(event_volume={1: EventVolume(total=5, by_event={"a": 5}, days=1)})

        assert provider.event_volume(1) is not None
        assert provider.event_volume(2) is None


class TestClickHouseStatisticsProvider(ClickhouseTestMixin, SimpleTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        sync_execute(SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL())
        sync_execute(DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL())
        sync_execute(WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL())

    def setUp(self) -> None:
        super().setUp()
        # A fresh team per test instead of a DELETE: a lightweight delete is a mutation on `team_id`, and it
        # can still apply to a part inserted right after it, which eats the rows the test just seeded.
        self.team_id = 4_000_000 + int(uuid4().int % 1_000_000)

    def _seed(self, rows: list[tuple[date, str, str, int]]) -> None:
        # (date, lib, event, count). Two libs on one day is how a real team splits, and it is what
        # the provider has to re-sum: the rollup is keyed by lib, the planner is not.
        values = ", ".join(
            f"('{d.isoformat()}', {self.team_id}, 'full', '{lib}', '{event}', "
            f"initializeAggregation('uniqExactState', (toUInt64(0), toUInt64(0), toUInt64(0))), "
            f"initializeAggregation('sumState', toUInt64({count})))"
            for d, lib, event, count in rows
        )
        sync_execute(
            f"INSERT INTO {WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE} "
            "(date, team_id, person_mode, lib, event, distinct_events_unique, event_count) "
            f"VALUES {values}"
        )

    def test_sums_across_libs_and_days_and_counts_distinct_days(self):
        self._seed(
            [
                (TODAY - timedelta(days=1), "web", "$pageview", 100),
                (TODAY - timedelta(days=1), "posthog-python", "$pageview", 20),
                (TODAY - timedelta(days=1), "web", "signup", 5),
                (TODAY - timedelta(days=3), "web", "$pageview", 80),
            ]
        )

        volume = ClickHouseStatisticsProvider(today=TODAY).event_volume(self.team_id)

        assert volume == EventVolume(total=205, by_event={"$pageview": 200, "signup": 5}, days=2)

    # The day past the window coincides with the table TTL, so it cannot be seeded reliably and is not a case here.
    @parameterized.expand(
        [
            ("today_is_partial_and_excluded", 0, 1),
            ("oldest_day_in_the_window_is_included", EVENT_VOLUME_WINDOW_DAYS, 1000),
        ]
    )
    def test_window_edges(self, _name, days_ago, expected_total):
        self._seed([(TODAY - timedelta(days=days_ago), "web", "$pageview", 999)])
        self._seed([(TODAY - timedelta(days=1), "web", "$pageview", 1)])

        volume = ClickHouseStatisticsProvider(today=TODAY).event_volume(self.team_id)

        assert volume is not None
        assert volume.total == expected_total

    def test_team_without_data_yields_none(self):
        assert ClickHouseStatisticsProvider(today=TODAY).event_volume(self.team_id) is None

    def test_memoizes_per_team_within_one_provider(self):
        self._seed([(TODAY - timedelta(days=1), "web", "$pageview", 7)])
        provider = ClickHouseStatisticsProvider(today=TODAY)

        with patch("posthog.hogql.cost.statistics.sync_execute", wraps=sync_execute) as execute:
            first = provider.event_volume(self.team_id)
            second = provider.event_volume(self.team_id)

        assert first == second
        assert execute.call_count == 1

    def test_clickhouse_failure_degrades_to_none(self):
        with patch("posthog.hogql.cost.statistics.sync_execute", side_effect=RuntimeError("boom")):
            assert ClickHouseStatisticsProvider(today=TODAY).event_volume(self.team_id) is None
