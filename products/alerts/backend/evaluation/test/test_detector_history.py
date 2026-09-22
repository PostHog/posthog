import re
from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.schema import HogQLAlertConfig

from products.alerts.backend.evaluation.detector_history import detector_rows_from_history
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.models.alert_series_point import AlertSeriesPoint
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


class _Warehouse:
    """Stands in for ClickHouse: holds a bucket->value series and answers narrowed scans from it."""

    def __init__(self, series: dict[datetime, float]) -> None:
        self.series = series
        self.overrides: list[dict | None] = []

    def run(self, query_override: dict | None = None) -> tuple[list, list[str] | None]:
        self.overrides.append(query_override)
        since = CURRENT_HOUR - timedelta(hours=self._hours(query_override))
        rows = [[bucket, value] for bucket, value in sorted(self.series.items()) if bucket >= since]
        return rows, ["bucket", "value"]

    @staticmethod
    def _hours(query_override: dict | None) -> int:
        if query_override is None:
            return 48
        return min(int(hours) for hours in re.findall(r"toIntervalHour\((\d+)\)", query_override["query"]))

    @property
    def last_scan_hours(self) -> int:
        return self._hours(self.overrides[-1])


class TestDetectorHistory(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, query={"kind": "HogQLQuery", "query": SQL})
        self.alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=self.insight,
            name="hourly count anomaly",
            condition={"type": "absolute_value"},
            detector_config={"type": "zscore", "window": 4},
            config={"type": "HogQLAlertConfig", "evaluation": "last_row", "column": "value"},
            calculation_interval="hourly",
        )
        self.config = HogQLAlertConfig.model_validate(self.alert.config)

    def _check(self, warehouse: _Warehouse) -> tuple[list, list[str]] | None:
        with patch(FLAG_PATH, return_value=True):
            return detector_rows_from_history(
                alert=self.alert,
                insight=self.alert.insight,
                config=self.config,
                min_samples=MIN_SAMPLES,
                run_query=warehouse.run,
            )

    @staticmethod
    def _dense(count: int, *, start_hours_ago: int = 1) -> dict[datetime, float]:
        return {CURRENT_HOUR - timedelta(hours=start_hours_ago + offset): float(10 + offset) for offset in range(count)}

    def _cached_buckets(self) -> list[datetime]:
        return sorted(
            AlertSeriesPoint.objects.for_team(self.team.pk)
            .filter(alert_config=self.alert)
            .values_list("bucket", flat=True)
        )

    def test_a_warm_cache_reads_only_the_recent_tail_and_returns_the_full_scan_series(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        with time_machine.travel(NOW, tick=False):
            first = self._check(warehouse)
            second = self._check(warehouse)

        assert first is not None and second is not None
        assert warehouse.overrides[0] is None
        assert warehouse.overrides[1] is not None
        assert warehouse.last_scan_hours == 3
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
        assert warehouse.last_scan_hours >= 9

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

        assert warehouse.overrides[-1] is None
        assert AlertSeriesPoint.objects.for_team(self.team.pk).filter(alert_config=self.alert).count() == 10

    def test_a_bucket_that_loses_its_events_loses_its_cached_value(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            emptied = CURRENT_HOUR - timedelta(hours=2)
            del warehouse.series[emptied]
            rows = self._check(warehouse)

        assert rows is not None
        assert emptied not in self._cached_buckets()
        assert emptied not in [bucket for bucket, _ in rows[0]]

    def test_too_few_cached_points_for_the_detector_fall_back_to_a_full_scan(self) -> None:
        warehouse = _Warehouse(self._dense(MIN_SAMPLES - 1))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
            self._check(warehouse)

        assert warehouse.overrides == [None, None]

    def test_deleting_the_alert_takes_its_cached_series_with_it(self) -> None:
        warehouse = _Warehouse(self._dense(10))
        with time_machine.travel(NOW, tick=False):
            self._check(warehouse)
        assert self._cached_buckets()

        alert_id = self.alert.id
        self.alert.delete()

        assert not AlertSeriesPoint.objects.for_team(self.team.pk).filter(alert_config_id=alert_id).exists()

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
