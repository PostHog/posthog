import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from hypothesis import (
    HealthCheck,
    given,
    settings,
    strategies as st,
)
from hypothesis.extra.django import TestCase as HypothesisDjangoTestCase
from parameterized import parameterized

from posthog.schema import HogQLAlertConfig

from products.alerts.backend.evaluation.detector_history import detector_rows_from_history
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.models.alert_series_point import AlertSeriesPoint, AlertSeriesState
from products.product_analytics.backend.facade.models import Insight

NOW = "2026-09-22T12:30:00Z"
CURRENT_HOUR = datetime(2026, 9, 22, 12, tzinfo=UTC)
MIN_SAMPLES = 5

SQL = """
SELECT toStartOfHour(timestamp) AS bucket, count() AS value
FROM events
WHERE timestamp >= toStartOfHour(now()) - INTERVAL 48 HOUR
  AND timestamp < toStartOfHour(now())
GROUP BY bucket
ORDER BY bucket ASC
"""
FLAG_PATH = "products.alerts.backend.evaluation.detector_history.feature_enabled_or_false"
RETENTION_PATH = "products.alerts.backend.evaluation.detector_history.events_retention_months_for_team"
RESTRICTIONS_PATH = (
    "products.alerts.backend.evaluation.detector_history.get_restricted_properties_with_group_type_index_for_team"
)
PROBE_PATH = "products.alerts.backend.evaluation.detector_history.sync_execute"


class _Warehouse:
    def __init__(self, series: dict[datetime, float]) -> None:
        self.series = series
        self.overrides: list[dict | None] = []

    def run(self, query_override: dict | None = None) -> tuple[list, list[str] | None]:
        self.overrides.append(query_override)
        buckets = self._buckets(query_override)
        window = self._window(query_override)
        rows = [
            [bucket, value]
            for bucket, value in sorted(self.series.items())
            if (buckets is None or bucket in buckets) and (window is None or window[0] <= bucket < window[1])
        ]
        return rows, ["bucket", "value"]

    @staticmethod
    def _window(query_override: dict | None) -> tuple[datetime, datetime] | None:
        """Honor the query's own pinned window, like the real SQL does. The pinned clock is the
        one mid-hour epoch; the INTERVAL is the query's own bound."""
        if query_override is None:
            return None
        sql = query_override["query"]
        pinned = [int(e) for e in re.findall(r"fromUnixTimestamp\((\d+)\)", sql) if int(e) % 3600]
        hours = re.findall(r"toIntervalHour\((\d+)\)", sql)
        if not pinned or not hours:
            return None
        floor = datetime.fromtimestamp(pinned[0] - pinned[0] % 3600, UTC)
        return floor - timedelta(hours=int(hours[0])), floor

    @staticmethod
    def _buckets(query_override: dict | None) -> set[datetime] | None:
        """The hour buckets a narrowed override reads, or None for a full scan.

        Pinned bucket constants are hour-aligned epochs; the pinned clock is mid-hour, so the
        alignment test separates the two.
        """
        if query_override is None:
            return None
        epochs = {
            int(epoch)
            for epoch in re.findall(r"fromUnixTimestamp\((\d+)\)", query_override["query"])
            if int(epoch) % 3600 == 0
        }
        if not epochs:
            return None
        return {datetime.fromtimestamp(epoch, UTC) for epoch in epochs}

    @property
    def last_scan_buckets(self) -> set[datetime]:
        buckets = self._buckets(self.overrides[-1])
        assert buckets is not None
        return buckets

    def is_rebuild(self, override: dict | None) -> bool:
        return self._buckets(override) is None


def _make_alert(team) -> AlertConfiguration:
    insight = Insight.objects.create(team=team, query={"kind": "HogQLQuery", "query": SQL})
    return AlertConfiguration.objects.create(
        team=team,
        insight=insight,
        name="hourly count anomaly",
        condition={"type": "absolute_value"},
        detector_config={"type": "zscore", "window": 4},
        config={"type": "HogQLAlertConfig", "evaluation": "last_row", "column": "value"},
        calculation_interval="hourly",
    )


def _flagged_check(
    alert: AlertConfiguration, config: HogQLAlertConfig, warehouse: _Warehouse, probe: list | Exception | None = None
) -> tuple[list, list[str]] | None:
    """Run a flagged check. ``probe`` is what the events_recent probe reports: changed buckets,
    an exception, or the default quiet result."""
    side_effect: Exception | None = probe if isinstance(probe, Exception) else None
    return_value = [] if probe is None or isinstance(probe, Exception) else [(bucket,) for bucket in probe]
    with (
        patch(FLAG_PATH, return_value=True),
        patch(PROBE_PATH, side_effect=side_effect, return_value=return_value),
    ):
        return detector_rows_from_history(
            alert=alert,
            insight=alert.insight,
            config=config,
            min_samples=MIN_SAMPLES,
            run_query=warehouse.run,
        )


class TestDetectorHistory(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.alert = _make_alert(self.team)
        self.insight = self.alert.insight
        self.config = HogQLAlertConfig.model_validate(self.alert.config)

    def _check(self, warehouse: _Warehouse, probe: list | Exception | None = None) -> tuple[list, list[str]] | None:
        return _flagged_check(self.alert, self.config, warehouse, probe)

    @staticmethod
    def _dense(count: int, *, start_hours_ago: int = 1) -> dict[datetime, float]:
        return {CURRENT_HOUR - timedelta(hours=start_hours_ago + offset): float(10 + offset) for offset in range(count)}

    def _cached_buckets(self) -> list[datetime]:
        return sorted(
            AlertSeriesPoint.objects.for_team(self.team.pk)
            .filter(alert_config=self.alert)
            .values_list("bucket", flat=True)
        )

    def test_the_tail_scan_carries_a_pinned_clock(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            self._check(warehouse)

        # The warehouse evaluating now() in a later hour than the app would strand a cached
        # bucket outside the authoritative range, so the narrowed query must not contain now().
        narrowed = warehouse.overrides[-1]
        assert narrowed is not None
        narrowed_sql = narrowed["query"]
        assert "now()" not in narrowed_sql
        assert "fromUnixTimestamp(" in narrowed_sql

    def test_a_warm_cache_reads_only_the_recent_tail_and_returns_the_full_scan_series(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        with time_machine.travel(NOW, tick=False):
            first = self._check(warehouse)
            second = self._check(warehouse)

        assert first is not None and second is not None
        assert warehouse.is_rebuild(warehouse.overrides[0])
        assert warehouse.overrides[1] is not None
        assert len(warehouse.last_scan_buckets) == 3
        assert second[0] == first[0]
        assert second[1] == ["bucket", "value"]

    def test_a_missed_check_widens_the_next_scan_to_reach_the_newest_cached_bucket(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)

        warehouse.series.update({CURRENT_HOUR + timedelta(hours=offset): 99.0 for offset in range(8)})
        with time_machine.travel("2026-09-22T20:30:00Z", tick=False):
            self._check(warehouse)

        # 8 hours since the newest cached bucket, plus an hour of clock-skew headroom.
        assert len(warehouse.last_scan_buckets) >= 9

    def test_an_hour_with_no_events_stays_absent_instead_of_becoming_a_zero(self) -> None:
        series = self._dense(10)
        missing = CURRENT_HOUR - timedelta(hours=4)
        del series[missing]
        warehouse = _Warehouse(series)

        with time_machine.travel(NOW, tick=False):
            rows = self._check(warehouse)

        assert rows is not None
        assert missing not in self._cached_buckets()
        assert [bucket for bucket, _ in rows[0]] == sorted(series)

    def test_editing_the_query_discards_the_cached_series(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            self.insight.query = {"kind": "HogQLQuery", "query": SQL.replace("count()", "uniq(person_id)")}
            self.insight.save()
            self.alert.refresh_from_db()
            self._check(warehouse)

        assert warehouse.is_rebuild(warehouse.overrides[-1])
        assert AlertSeriesPoint.objects.for_team(self.team.pk).filter(alert_config=self.alert).count() == 10

    def test_changing_the_team_timezone_discards_the_cached_series(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            self.team.timezone = "Asia/Kathmandu"
            self.team.save(update_fields=["timezone"])
            self._check(warehouse)

        # Cached buckets were aligned under the old timezone, so the new one must rebuild.
        assert warehouse.is_rebuild(warehouse.overrides[-1])

    def test_a_first_row_alert_is_not_served_from_the_cache(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        first_row = HogQLAlertConfig.model_validate({**(self.alert.config or {}), "evaluation": "first_row"})
        with time_machine.travel(NOW, tick=False), patch(FLAG_PATH, return_value=True):
            rows = detector_rows_from_history(
                alert=self.alert,
                insight=self.alert.insight,
                config=first_row,
                min_samples=MIN_SAMPLES,
                run_query=warehouse.run,
            )

        # first_row scores the oldest bucket, which the tail refresh never re-reads.
        assert rows is None
        assert warehouse.overrides == []

    def test_a_dst_fold_inside_the_window_falls_back_to_full_scans(self) -> None:
        self.team.timezone = "Europe/Amsterdam"
        self.team.save(update_fields=["timezone"])
        warehouse = _Warehouse(self._dense(10))
        # Amsterdam left DST on 2026-10-25 01:00 UTC; a 48h window from the 26th spans it.
        with time_machine.travel("2026-10-26T12:30:00Z", tick=False):
            rows = self._check(warehouse)

        assert rows is None
        assert warehouse.overrides == []

    def test_changing_team_modifiers_discards_the_cached_series(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            self.team.modifiers = {"convertToProjectTimezone": False}
            self.team.save(update_fields=["modifiers"])
            self._check(warehouse)

        assert warehouse.is_rebuild(warehouse.overrides[-1])

    def test_a_retention_floor_change_discards_the_cached_series(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            with patch(RETENTION_PATH, return_value=12):
                self._check(warehouse)

        assert warehouse.is_rebuild(warehouse.overrides[-1])

    def test_changing_property_access_restrictions_discards_the_cached_series(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        restriction = SimpleNamespace(name="plan", property_type="event", group_type_index=None)
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            with patch(RESTRICTIONS_PATH, return_value=[restriction]):
                self._check(warehouse)

        # Cached buckets were computed before the property was restricted, so they must go.
        assert warehouse.is_rebuild(warehouse.overrides[-1])

    @parameterized.expand([("inside_the_margin", 2), ("at_the_scan_boundary", 3)])
    def test_a_bucket_that_loses_its_events_loses_its_cached_value(self, _name: str, hours_ago: int) -> None:
        warehouse = _Warehouse(self._dense(10))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            emptied = CURRENT_HOUR - timedelta(hours=hours_ago)
            del warehouse.series[emptied]
            rows = self._check(warehouse)

        assert rows is not None
        assert emptied not in self._cached_buckets()
        assert emptied not in [bucket for bucket, _ in rows[0]]

    def test_the_oldest_bucket_of_the_window_survives_a_mid_hour_check(self) -> None:
        warehouse = _Warehouse(self._dense(48))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            rows = self._check(warehouse)

        assert rows is not None
        assert len(warehouse.last_scan_buckets) < 48
        assert next(bucket for bucket, _ in rows[0]) == CURRENT_HOUR - timedelta(hours=48)
        assert len(rows[0]) == 48

    def test_too_few_cached_points_for_the_detector_fall_back_to_a_full_scan(self) -> None:
        warehouse = _Warehouse(self._dense(MIN_SAMPLES - 1))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            self._check(warehouse)

        assert len(warehouse.overrides) == 2
        assert all(warehouse.is_rebuild(o) for o in warehouse.overrides)

    def test_deleting_the_alert_takes_its_cached_series_with_it(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
        assert self._cached_buckets()

        alert_id = self.alert.id
        self.alert.delete()

        assert not AlertSeriesPoint.objects.for_team(self.team.pk).filter(alert_config_id=alert_id).exists()

    def test_a_probed_late_bucket_is_rescanned_and_its_new_value_served(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        late = CURRENT_HOUR - timedelta(hours=8)
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            warehouse.series[late] = 77.0
            rows = self._check(warehouse, probe=[late])

        assert rows is not None
        assert late in warehouse.last_scan_buckets
        assert (late, 77.0) in [(bucket, value) for bucket, value in rows[0]]

    def test_an_assembly_reaching_the_query_limit_reruns_the_full_scan(self) -> None:
        limited = SQL.replace("ORDER BY bucket ASC", "ORDER BY bucket ASC LIMIT 8")
        self.insight.query = {"kind": "HogQLQuery", "query": limited}
        self.insight.save()
        self.alert.refresh_from_db()
        warehouse = _Warehouse(self._dense(7, start_hours_ago=4))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            warehouse.series.update(self._dense(2))
            self._check(warehouse)

        # 7 cached + margin growth reaches the LIMIT of 8; only the full query's completeness
        # probe can say whether the result is truncated, so the cache must not decide.
        assert warehouse.is_rebuild(warehouse.overrides[-1])

    def test_a_watermark_older_than_the_probe_horizon_reruns_the_full_scan(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            AlertSeriesState.objects.for_team(self.team.pk).filter(alert_config=self.alert).update(
                watermark=CURRENT_HOUR - timedelta(days=9), seeded_at=CURRENT_HOUR
            )
            self._check(warehouse)

        assert warehouse.is_rebuild(warehouse.overrides[-1])

    def test_probed_buckets_outside_the_window_are_ignored(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        too_old = CURRENT_HOUR - timedelta(hours=60)
        in_progress = CURRENT_HOUR
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            rows = self._check(warehouse, probe=[too_old, in_progress])

        # A late insert for a bucket the window no longer covers, or for the still-open hour
        # the query excludes, must not widen the rescan.
        assert rows is not None
        assert too_old not in warehouse.last_scan_buckets
        assert in_progress not in warehouse.last_scan_buckets
        assert len(warehouse.last_scan_buckets) == 3

    def test_a_failed_probe_still_serves_the_margin_scan_and_keeps_the_watermark(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            state_before = AlertSeriesState.objects.for_team(self.team.pk).get(alert_config=self.alert)
            rows = self._check(warehouse, probe=RuntimeError("probe outage"))
            state_after = AlertSeriesState.objects.for_team(self.team.pk).get(alert_config=self.alert)

        assert rows is not None
        assert len(warehouse.last_scan_buckets) == 3
        # An unadvanced watermark makes the next successful probe re-detect the interval.
        assert state_after.watermark == state_before.watermark

    def test_a_stale_seed_triggers_a_scheduled_full_rescan(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            AlertSeriesState.objects.for_team(self.team.pk).filter(alert_config=self.alert).update(
                seeded_at=CURRENT_HOUR - timedelta(hours=25)
            )
            self._check(warehouse)

        # Person merges and dedup collapses leave no insert signal, so age alone reseeds.
        assert warehouse.is_rebuild(warehouse.overrides[-1])

    def test_cached_buckets_without_a_watermark_trigger_a_full_rescan(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            AlertSeriesState.objects.for_team(self.team.pk).filter(alert_config=self.alert).delete()
            self._check(warehouse)

        assert warehouse.is_rebuild(warehouse.overrides[-1])

    def test_the_flag_being_off_leaves_the_check_and_the_cache_untouched(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        with time_machine.travel(NOW, tick=False), patch(FLAG_PATH, return_value=False):
            result = detector_rows_from_history(
                alert=self.alert,
                insight=self.alert.insight,
                config=self.config,
                min_samples=MIN_SAMPLES,
                run_query=warehouse.run,
            )

        assert result is None
        assert warehouse.overrides == []
        assert not self._cached_buckets()


class TestDetectorHistorySpec(HypothesisDjangoTestCase, BaseTest):
    """The cache's executable contract, searched by hypothesis rather than enumerated."""

    def setUp(self) -> None:
        super().setUp()
        self.alert = _make_alert(self.team)
        self.config = HogQLAlertConfig.model_validate(self.alert.config)

    @given(
        offsets=st.dictionaries(
            st.integers(1, 47),
            st.floats(0, 1e6, allow_nan=False, allow_infinity=False),
            min_size=MIN_SAMPLES + 1,
            max_size=40,
        ),
        late=st.lists(
            st.tuples(st.integers(0, 4), st.integers(1, 47), st.floats(0, 1e6, allow_nan=False, allow_infinity=False)),
            max_size=6,
        ),
        gaps=st.lists(st.integers(1, 30), min_size=2, max_size=5),
    )
    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_the_cache_always_equals_the_full_scan(
        self, offsets: dict[int, float], late: list[tuple[int, int, float]], gaps: list[int]
    ) -> None:
        """For any history, any late-arrival pattern, and any check schedule (missed checks,
        reseed crossings), the served series equals what the full scan returns at that instant.
        Hypothesis shrinks any counterexample to its minimal form."""
        warehouse = _Warehouse({CURRENT_HOUR - timedelta(hours=h): v for h, v in offsets.items()})
        t = datetime(2026, 9, 22, 12, 30, tzinfo=UTC)
        for index, gap in enumerate(gaps):
            t += timedelta(hours=gap)
            anchor = t.replace(minute=0, second=0, microsecond=0)
            arrivals = [(anchor - timedelta(hours=h), v) for (i, h, v) in late if i == index]
            for bucket, value in arrivals:
                warehouse.series[bucket] = value
            with time_machine.travel(t, tick=False):
                result = _flagged_check(self.alert, self.config, warehouse, probe=[b for b, _ in arrivals])
            assert result is not None
            expected = [
                [bucket, warehouse.series[bucket]]
                for bucket in sorted(warehouse.series)
                if anchor - timedelta(hours=48) <= bucket < anchor
            ][-48:]
            assert result[0] == expected
