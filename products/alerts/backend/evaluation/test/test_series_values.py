from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.alerts.backend.evaluation.dispatcher import check_alert_for_insight
from products.alerts.backend.evaluation.series_values_shadow import SHADOW_BUILD_BUDGET_SECONDS, SHADOW_COMPARISON_EVENT
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
        insight = Insight.objects.create(team=self.team, query=_trends_query(interval))
        return AlertConfiguration.objects.create(
            team=self.team,
            insight=insight,
            created_by=self.user,
            name="signups",
            condition={"type": "absolute_value"},
            config={"type": "TrendsAlertConfig", "series_index": 0},
            calculation_interval="daily" if interval == "day" else "hourly",
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
        assert cold_properties["buckets_compared"] > 0
        assert cold_properties["alert_kind"] == ("detector" if detector else "threshold")
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
                (team_id, job_id, time_window_start, series_key, breakdown_value, value)
            VALUES (%(team_id)s, %(job_id)s, '2024-01-14 10:00:00', '', [], 1)
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
