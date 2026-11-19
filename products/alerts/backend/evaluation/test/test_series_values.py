from datetime import UTC, date, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from temporalio.exceptions import CancelledError

from posthog.schema import TrendsQuery

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.services.query import ExecutionMode
from posthog.caching.insight_result import InsightResult
from posthog.clickhouse.client import sync_execute
from posthog.errors import CHQueryErrorQueryWasCancelled
from posthog.models.team import Team
from posthog.models.user import User

from products.alerts.backend.evaluation.dispatcher import check_alert_for_insight, run_extractor
from products.alerts.backend.evaluation.series_values_shadow import (
    SHADOW_BUILD_BUDGET_SECONDS,
    SHADOW_COMPARISON_EVENT,
    compare_closed_sql_values,
    compare_series_values_shadow,
)
from products.alerts.backend.models.alert import AlertConfiguration, Threshold
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.product_analytics.backend.facade.contracts import ClosedSqlSeriesValues
from products.product_analytics.backend.facade.models import Insight

_NOW = "2024-01-15T12:00:00Z"
_SHADOW = "products.alerts.backend.evaluation.series_values_shadow"

_THRESHOLD_DETECTOR = {"type": "threshold", "upper_bound": 100.0}
_ZSCORE_DETECTOR = {"type": "zscore", "window": 24}


def _shadow_events(capture: MagicMock) -> list[dict[str, Any]]:
    return [
        call.kwargs["properties"]
        for call in capture.call_args_list
        if call.kwargs.get("event") == SHADOW_COMPARISON_EVENT
    ]


_DAILY_SQL = {
    "kind": "HogQLQuery",
    "query": "SELECT toStartOfDay(timestamp) AS day, count() AS value FROM events GROUP BY day ORDER BY day",
}


def _trends_query(interval: str) -> dict[str, Any]:
    return {
        "kind": "TrendsQuery",
        "series": [{"kind": "EventsNode", "event": "signed_up", "math": "total"}],
        "interval": interval,
        "dateRange": {"date_from": "-7d" if interval == "day" else "-24h"},
    }


def _create_alert(
    team: Team,
    user: User,
    query: dict[str, Any],
    config: dict[str, Any],
    detector: dict[str, Any] | None,
    calculation_interval: str,
) -> AlertConfiguration:
    insight = Insight.objects.create(team=team, query=query)
    return AlertConfiguration.objects.create(
        team=team,
        insight=insight,
        created_by=user,
        name="signups",
        condition={"type": "absolute_value"},
        config=config,
        calculation_interval=calculation_interval,
        detector_config=detector,
        threshold=None
        if detector
        else Threshold.objects.create(
            team=team, insight=insight, name="t", configuration={"type": "absolute", "bounds": {"upper": 100}}
        ),
    )


@override_settings(IN_UNIT_TESTING=True)
@time_machine.travel(_NOW, tick=False)
class TestSeriesValuesShadowForAlerts(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()
        sync_execute("SYSTEM STOP TTL MERGES sharded_series_values_preaggregated")
        self.addCleanup(sync_execute, "SYSTEM START TTL MERGES sharded_series_values_preaggregated")
        for timestamp in (
            "2024-01-13T05:00:00Z",
            "2024-01-14T07:00:00Z",
            "2024-01-14T08:00:00Z",
            "2024-01-14T20:15:00Z",
            "2024-01-15T09:00:00Z",
            "2024-01-15T10:20:00Z",
            "2024-01-15T11:10:00Z",
        ):
            _create_event(team=self.team, event="signed_up", distinct_id="p1", timestamp=timestamp)
        flush_persons_and_events()

    def _alert(self, *, detector: dict[str, Any] | None, interval: str = "day") -> AlertConfiguration:
        return self._alert_on(
            _trends_query(interval),
            {"type": "TrendsAlertConfig", "series_index": 0},
            detector=detector,
            calculation_interval="daily" if interval == "day" else "hourly",
        )

    def _sql_alert(self, *, detector: dict[str, Any] | None) -> AlertConfiguration:
        return self._alert_on(
            _DAILY_SQL,
            {"type": "HogQLAlertConfig", "evaluation": "last_row", "column": "value"},
            detector=detector,
            calculation_interval="daily",
        )

    def _alert_on(
        self,
        query: dict[str, Any],
        config: dict[str, Any],
        *,
        detector: dict[str, Any] | None,
        calculation_interval: str,
    ) -> AlertConfiguration:
        return _create_alert(self.team, self.user, query, config, detector, calculation_interval)

    def _enrolled(self) -> Any:
        return override_settings(ALERTS_SERIES_VALUES_PRECOMPUTE_TEAM_IDS=[self.team.pk])

    def _jobs(self) -> int:
        return PreaggregationJob.objects.filter(team_id=self.team.pk).count()

    def _insert_execution_limits(self) -> set[str]:
        sync_execute("SYSTEM FLUSH LOGS")
        rows = sync_execute(
            """
            SELECT DISTINCT Settings['max_execution_time']
            FROM system.query_log
            WHERE type = 'QueryFinish'
              AND query_kind = 'Insert'
              AND JSONExtractString(log_comment, 'client_query_id') IN %(job_ids)s
            """,
            {
                "job_ids": [
                    str(job_id)
                    for job_id in PreaggregationJob.objects.filter(team_id=self.team.pk).values_list("id", flat=True)
                ]
            },
        )
        return {row[0] for row in rows}

    def _shadowed_check(self, alert: AlertConfiguration) -> tuple[Any, dict[str, Any]]:
        with self._enrolled(), patch(f"{_SHADOW}.posthoganalytics.capture") as capture:
            result = check_alert_for_insight(alert)
        [properties] = _shadow_events(capture)
        return result, properties

    @parameterized.expand(
        [
            ("threshold_daily", None, "day", _NOW),
            ("detector_daily", _THRESHOLD_DETECTOR, "day", _NOW),
            ("detector_hourly_off_the_hour", _ZSCORE_DETECTOR, "hour", "2024-01-15T12:37:00Z"),
        ]
    )
    def test_first_check_builds_stored_values_and_later_checks_reuse_them(
        self, _name: str, detector: dict[str, Any] | None, interval: str, now: str
    ) -> None:
        alert = self._alert(detector=detector, interval=interval)
        with time_machine.travel(now, tick=False):
            live = check_alert_for_insight(alert)
            assert self._jobs() == 0

            cold, cold_properties = self._shadowed_check(alert)
            jobs_after_build = self._jobs()
            warm, warm_properties = self._shadowed_check(alert)

        assert cold == live
        assert warm == live
        assert jobs_after_build > 0
        assert self._jobs() == jobs_after_build
        assert (cold_properties["outcome"], cold_properties["freshly_built"]) == ("match", True)
        assert (warm_properties["outcome"], warm_properties["freshly_built"]) == ("match", False)
        assert (cold_properties["verified"], cold_properties["stale_days"]) == (True, 0)
        assert isinstance(cold_properties["verify_duration_ms"], int)
        assert (warm_properties["verified"], warm_properties["stale_days"], warm_properties["verify_duration_ms"]) == (
            False,
            0,
            None,
        )
        assert cold_properties["buckets_compared"] > 0
        assert cold_properties["alert_kind"] == ("detector" if detector else "threshold")
        assert cold_properties["insight_kind"] == "trends"
        assert self._insert_execution_limits() == {str(SHADOW_BUILD_BUDGET_SECONDS)}

    @parameterized.expand([("threshold", None), ("detector", _THRESHOLD_DETECTOR)])
    def test_a_mismatch_never_changes_the_check(self, _name: str, detector: dict[str, Any] | None) -> None:
        alert = self._alert(detector=detector)
        live = check_alert_for_insight(alert)
        self._shadowed_check(alert)
        job = PreaggregationJob.objects.get(
            team_id=self.team.pk,
            time_range_start__lte="2024-01-14T00:00:00Z",
            time_range_end__gt="2024-01-14T00:00:00Z",
        )
        sync_execute(
            """
            INSERT INTO sharded_series_values_preaggregated
                (team_id, job_id, time_window_start, series_key, value)
            VALUES (%(team_id)s, %(job_id)s, '2024-01-14 10:00:00', '', 1)
            """,
            {"team_id": self.team.pk, "job_id": str(job.id)},
        )

        shadowed, properties = self._shadowed_check(alert)

        assert shadowed == live
        assert (properties["outcome"], properties["max_abs_difference"]) == ("mismatch", 1.0)

    def test_a_failing_shadow_step_records_an_error_and_never_changes_the_check(self) -> None:
        alert = self._alert(detector=_THRESHOLD_DETECTOR)
        live = check_alert_for_insight(alert)

        with patch(f"{_SHADOW}.closed_series_values", side_effect=RuntimeError("boom")):
            shadowed, properties = self._shadowed_check(alert)

        assert shadowed == live
        assert (properties["outcome"], properties["reason"]) == ("error", "RuntimeError")

    @parameterized.expand(
        [
            ("killed_query", CHQueryErrorQueryWasCancelled("killed", code=394)),
            ("cancelled_activity", CancelledError()),
        ]
    )
    def test_a_cancelled_check_stops_in_the_shadow_step(self, _name: str, cancellation: Exception) -> None:
        alert = self._alert(detector=_THRESHOLD_DETECTOR)

        with (
            self._enrolled(),
            patch(f"{_SHADOW}.closed_series_values", side_effect=cancellation),
            patch(f"{_SHADOW}.posthoganalytics.capture") as capture,
            self.assertRaises(type(cancellation)),
        ):
            check_alert_for_insight(alert)

        assert _shadow_events(capture) == []

    @parameterized.expand([("no_results", None), ("empty_results", [])])
    def test_an_empty_live_result_builds_nothing(self, _name: str, live: list | None) -> None:
        alert = self._alert(detector=None)

        with self._enrolled(), patch(f"{_SHADOW}.posthoganalytics.capture") as capture:
            compare_series_values_shadow(
                alert,
                TrendsQuery.model_validate(_trends_query("day")),
                None,
                InsightResult(result=live, last_refresh=None, cache_key=None, is_cached=False, timezone=None),
                alert_kind="threshold",
            )

        [properties] = _shadow_events(capture)
        assert (properties["outcome"], properties["reason"]) == ("unavailable", "no_live_result")
        assert self._jobs() == 0

    @parameterized.expand(
        [
            ("flag_off", {"return_value": False}, 0),
            ("flag_check_raises", {"side_effect": RuntimeError("flags down")}, 0),
            ("flag_on", {"return_value": True}, 1),
        ]
    )
    def test_enrollment_by_flag(self, _name: str, flag: dict[str, Any], shadow_events: int) -> None:
        alert = self._alert(detector=None)
        live = check_alert_for_insight(alert)

        with (
            patch(f"{_SHADOW}.posthoganalytics.feature_enabled", **flag),
            patch(f"{_SHADOW}.posthoganalytics.capture") as capture,
        ):
            checked = check_alert_for_insight(alert)

        assert checked == live
        assert len(_shadow_events(capture)) == shadow_events
        assert (self._jobs() > 0) == bool(shadow_events)

    def test_a_cancelled_sql_alert_check_stops_while_recording(self) -> None:
        alert = self._sql_alert(detector=None)

        def cancel_on_shadow_event(**kwargs: Any) -> None:
            if kwargs.get("event") == SHADOW_COMPARISON_EVENT:
                raise CancelledError()

        with (
            self._enrolled(),
            patch(f"{_SHADOW}.posthoganalytics.capture", side_effect=cancel_on_shadow_event),
            self.assertRaises(CancelledError),
        ):
            check_alert_for_insight(alert)


_WINDOWED_SQL = (
    "SELECT toStartOfDay(timestamp) AS day, count() AS value FROM events "
    "WHERE timestamp >= now() - INTERVAL 7 DAY AND event = 'signed_up' GROUP BY day ORDER BY day"
)
_SQL_CONFIG = {"type": "HogQLAlertConfig", "evaluation": "last_row"}


@override_settings(IN_UNIT_TESTING=True)
class TestSeriesValuesShadowForSqlAlerts(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()
        sync_execute("SYSTEM STOP TTL MERGES sharded_series_values_preaggregated")
        self.addCleanup(sync_execute, "SYSTEM START TTL MERGES sharded_series_values_preaggregated")
        clickhouse_now = sync_execute("SELECT now64(6, 'UTC')")[0][0]
        traveller = time_machine.travel(clickhouse_now, tick=False)
        traveller.start()
        self.addCleanup(traveller.stop)
        today = clickhouse_now.replace(hour=0, minute=0, second=0, microsecond=0)
        for days_ago, hour in ((6, 5), (4, 7), (4, 8), (2, 20), (1, 1), (1, 23), (0, 0)):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="p1",
                timestamp=today - timedelta(days=days_ago) + timedelta(hours=hour),
            )
        flush_persons_and_events()

    def _sql_alert(self, sql: str, *, detector: dict[str, Any] | None) -> AlertConfiguration:
        return _create_alert(self.team, self.user, {"kind": "HogQLQuery", "query": sql}, _SQL_CONFIG, detector, "daily")

    def _jobs(self) -> int:
        return PreaggregationJob.objects.filter(team_id=self.team.pk).count()

    @parameterized.expand(
        [
            ("threshold", _WINDOWED_SQL, None, True, ("match", None)),
            ("detector", _WINDOWED_SQL, _THRESHOLD_DETECTOR, True, ("match", None)),
            ("ineligible_query", _DAILY_SQL["query"], None, True, ("unavailable", "window")),
            ("unenrolled", _WINDOWED_SQL, None, False, None),
        ]
    )
    def test_an_enrolled_check_records_one_comparison_and_keeps_its_result(
        self,
        _name: str,
        sql: str,
        detector: dict[str, Any] | None,
        enrolled: bool,
        expected: tuple[str, str | None] | None,
    ) -> None:
        alert = self._sql_alert(sql, detector=detector)
        live = check_alert_for_insight(alert)

        with (
            patch(f"{_SHADOW}.posthoganalytics.feature_enabled", return_value=enrolled),
            patch(f"{_SHADOW}.posthoganalytics.capture") as capture,
        ):
            checked = check_alert_for_insight(alert)

        events = _shadow_events(capture)
        assert checked == live
        assert [(properties["outcome"], properties["reason"]) for properties in events] == (
            [expected] if expected else []
        )
        if expected == ("match", None):
            [properties] = events
            assert properties["buckets_compared"] >= 3
            assert (properties["insight_kind"], properties["alert_kind"]) == (
                "HogQLQuery",
                "detector" if detector else "threshold",
            )
            assert properties["verified"] is False
        assert (self._jobs() > 0) == (expected == ("match", None))

    def test_a_user_facing_query_error_in_the_shadow_never_disables_the_alert(self) -> None:
        alert = self._sql_alert(_WINDOWED_SQL, detector=None)
        live = check_alert_for_insight(alert)

        with (
            self.settings(ALERTS_SERIES_VALUES_PRECOMPUTE_TEAM_IDS=[self.team.pk]),
            patch(f"{_SHADOW}.closed_sql_series_values", side_effect=ExposedHogQLError("bad column")),
            patch(f"{_SHADOW}.posthoganalytics.capture") as capture,
        ):
            checked = check_alert_for_insight(alert)

        alert.refresh_from_db()
        [properties] = _shadow_events(capture)
        assert checked == live
        assert alert.enabled
        assert (properties["outcome"], properties["reason"]) == ("error", "ExposedHogQLError")

    @parameterized.expand(
        [
            ("trends", "TrendsQuery", []),
            ("sql", "HogQLQuery", []),
            ("funnels", "FunnelsQuery", [("unavailable", "unsupported_insight_kind", "FunnelsQuery")]),
        ]
    )
    def test_only_kinds_without_their_own_comparison_record_unsupported(
        self, _name: str, kind: str, expected: list[tuple[str, str, str]]
    ) -> None:
        alert = self._sql_alert(_WINDOWED_SQL, detector=None)
        extractor = MagicMock()

        with (
            self.settings(ALERTS_SERIES_VALUES_PRECOMPUTE_TEAM_IDS=[self.team.pk]),
            patch(f"{_SHADOW}.posthoganalytics.capture") as capture,
        ):
            run_extractor(extractor, alert, alert.insight, {"kind": kind}, ExecutionMode.CALCULATE_BLOCKING_ALWAYS)

        assert [
            (properties["outcome"], properties["reason"], properties["insight_kind"])
            for properties in _shadow_events(capture)
        ] == expected


_TODAY = datetime(2024, 1, 15, tzinfo=UTC)


def _day(day: int) -> datetime:
    return datetime(2024, 1, day, tzinfo=UTC)


class TestCompareClosedSqlValues(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "clipped_first_bucket_and_today_are_skipped",
                [["2024-01-10T00:00:00Z", 1], [_day(11), 5], [date(2024, 1, 12), None], [_day(15), 9]],
                {_day(10): 3.0, _day(11): 5.0},
                ("match", 2, 0.0),
            ),
            (
                "a_row_missing_on_one_side_is_a_mismatch",
                [[_day(10), 1], [_day(11), 5], [_day(13), 2]],
                {_day(11): 5.0, _day(12): 4.0, _day(13): 2.0},
                ("mismatch", 3, 4.0),
            ),
            (
                "buckets_after_the_last_live_row_are_skipped",
                [[_day(14), 3], [_day(13), 2], [_day(12), 1]],
                {_day(11): 8.0, _day(12): 1.0, _day(13): 2.0, _day(14): 3.0},
                ("match", 2, 0.0),
            ),
            (
                "float_noise_within_tolerance_matches",
                [[_day(10), 1], [_day(11), 0.1 + 0.2]],
                {_day(11): 0.3},
                ("match", 1, abs(0.1 + 0.2 - 0.3)),
            ),
        ]
    )
    def test_compares_closed_buckets_after_the_first_live_row(
        self, _name: str, rows: list, stored: dict[datetime, float], expected: tuple[str, int, float]
    ) -> None:
        closed = ClosedSqlSeriesValues(bucket_column="day", values=stored, closed_before=_TODAY)

        comparison = compare_closed_sql_values(closed, rows, ["day", "value"], "value")

        assert (comparison.outcome, comparison.buckets_compared, comparison.max_abs_difference) == expected
