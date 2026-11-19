from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from temporalio.exceptions import CancelledError

from posthog.schema import TrendsQuery

from posthog.caching.insight_result import InsightResult
from posthog.clickhouse.client import sync_execute
from posthog.errors import CHQueryErrorQueryWasCancelled

from products.alerts.backend.evaluation.dispatcher import check_alert_for_insight
from products.alerts.backend.evaluation.series_values_shadow import (
    SHADOW_BUILD_BUDGET_SECONDS,
    SHADOW_COMPARISON_EVENT,
    compare_series_values_shadow,
)
from products.alerts.backend.models.alert import AlertConfiguration, Threshold
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
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
        insight = Insight.objects.create(team=self.team, query=query)
        return AlertConfiguration.objects.create(
            team=self.team,
            insight=insight,
            created_by=self.user,
            name="signups",
            condition={"type": "absolute_value"},
            config=config,
            calculation_interval=calculation_interval,
            detector_config=detector,
            threshold=None
            if detector
            else Threshold.objects.create(
                team=self.team, insight=insight, name="t", configuration={"type": "absolute", "bounds": {"upper": 100}}
            ),
        )

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

    @parameterized.expand(
        [
            ("enrolled_threshold", True, None, "threshold"),
            ("enrolled_detector", True, _THRESHOLD_DETECTOR, "detector"),
            ("unenrolled", False, None, None),
        ]
    )
    def test_a_sql_alert_check_records_it_is_not_covered(
        self, _name: str, enrolled: bool, detector: dict[str, Any] | None, alert_kind: str | None
    ) -> None:
        alert = self._sql_alert(detector=detector)
        live = check_alert_for_insight(alert)

        with (
            patch(f"{_SHADOW}.posthoganalytics.feature_enabled", return_value=enrolled),
            patch(f"{_SHADOW}.posthoganalytics.capture") as capture,
        ):
            checked = check_alert_for_insight(alert)

        assert checked == live
        assert [
            {key: properties[key] for key in ("outcome", "reason", "insight_kind", "alert_kind", "alert_id")}
            for properties in _shadow_events(capture)
        ] == (
            [
                {
                    "outcome": "unavailable",
                    "reason": "unsupported_insight_kind",
                    "insight_kind": "HogQLQuery",
                    "alert_kind": alert_kind,
                    "alert_id": str(alert.id),
                }
            ]
            if enrolled
            else []
        )
        assert self._jobs() == 0

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
