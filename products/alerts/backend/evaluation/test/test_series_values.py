from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager, nullcontext
from datetime import datetime
from typing import Any
from uuid import uuid4

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from temporalio.exceptions import CancelledError

from posthog.schema import TrendsQuery

from posthog.caching.insight_result import InsightResult
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import default_client
from posthog.clickhouse.query_tagging import get_query_tags, tags_context
from posthog.errors import CHQueryErrorQueryWasCancelled
from posthog.test.waiting import wait_until

from products.alerts.backend.evaluation.dispatcher import check_alert_for_insight
from products.alerts.backend.evaluation.query_slot import QuerySlotFull
from products.alerts.backend.evaluation.series_values_shadow import (
    SHADOW_BUILD_BUDGET_SECONDS,
    SHADOW_COMPARISON_EVENT,
    SHADOW_READ_MAX_SECONDS,
    collecting_shadow_comparisons,
    compare_precomputed_values,
    compare_series_values_shadow,
    effective_trends_runner,
)
from products.alerts.backend.models.alert import AlertConfiguration, Threshold
from products.alerts.backend.platform_source_cycle import QUERY_ID_PREFIX, stop_insight_queries
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.product_analytics.backend.facade.contracts import PrecomputedSeriesValues
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


@contextmanager
def _query_slot() -> Iterator[None]:
    yield


def _platform_check(
    alert: AlertConfiguration, query_slot: Callable[[], AbstractContextManager[object]] = _query_slot
) -> Any:
    with collecting_shadow_comparisons() as comparisons:
        result = check_alert_for_insight(alert)
    for comparison in comparisons:
        comparison.run(query_slot)
    return result


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
        return patch(f"{_SHADOW}.posthoganalytics.feature_enabled", return_value=True)

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

    def _stored_read_execution_limits(self) -> set[str]:
        sync_execute("SYSTEM FLUSH LOGS")
        rows = sync_execute(
            """
            SELECT DISTINCT Settings['max_execution_time']
            FROM system.query_log
            WHERE type = 'QueryFinish'
              AND query_kind = 'Select'
              AND query LIKE '%%series_values_preaggregated%%'
              AND query LIKE '%%day_start%%'
              AND JSONExtractInt(log_comment, 'team_id') = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )
        return {row[0] for row in rows}

    def _shadowed_check(self, alert: AlertConfiguration) -> tuple[Any, dict[str, Any]]:
        with self._enrolled(), patch(f"{_SHADOW}.posthoganalytics.capture") as capture:
            result = _platform_check(alert)
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
        assert cold_properties["insight_kind"] == "trends"
        limits = self._insert_execution_limits()
        assert limits and all(1 <= int(limit) <= SHADOW_BUILD_BUDGET_SECONDS for limit in limits)
        assert self._stored_read_execution_limits() == {str(SHADOW_READ_MAX_SECONDS)}

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
                (team_id, job_id, time_window_start, time_window_end, series_key, value)
            VALUES (%(team_id)s, %(job_id)s, '2024-01-14 10:00:00', '2024-01-14 11:00:00', '', 1)
            """,
            {"team_id": self.team.pk, "job_id": str(job.id)},
        )

        shadowed, properties = self._shadowed_check(alert)

        assert shadowed == live
        assert (properties["outcome"], properties["max_abs_difference"]) == ("mismatch", 1.0)

    def test_a_failing_shadow_step_records_an_error_and_never_changes_the_check(self) -> None:
        alert = self._alert(detector=_THRESHOLD_DETECTOR)
        live = check_alert_for_insight(alert)

        with patch(f"{_SHADOW}.precomputed_series_values", side_effect=RuntimeError("boom")):
            shadowed, properties = self._shadowed_check(alert)

        assert shadowed == live
        assert (properties["outcome"], properties["reason"]) == ("error", "RuntimeError")

    def test_a_check_without_time_for_the_build_skips_it(self) -> None:
        alert = self._alert(detector=None)
        live = check_alert_for_insight(alert)

        with patch(f"{_SHADOW}.attempt_outlasts", return_value=False):
            shadowed, properties = self._shadowed_check(alert)

        assert shadowed == live
        assert (properties["outcome"], properties["reason"]) == ("unavailable", "attempt_out_of_time")
        assert self._jobs() == 0

    def test_a_compared_check_records_the_features_its_query_used(self) -> None:
        plan_filter = {"key": "plan", "value": "pro", "operator": "exact", "type": "event"}
        alert = self._alert_on(
            {**_trends_query("day"), "properties": [plan_filter]},
            {"type": "TrendsAlertConfig", "series_index": 0},
            detector=None,
            calculation_interval="daily",
        )

        _, properties = self._shadowed_check(alert)

        assert properties["features"] == ["event_name", "event_property_filters"]

    def test_a_check_that_nobody_collects_for_is_not_shadowed(self) -> None:
        alert = self._alert(detector=None)

        with self._enrolled(), patch(f"{_SHADOW}.posthoganalytics.capture") as capture:
            check_alert_for_insight(alert)

        assert _shadow_events(capture) == []
        assert self._jobs() == 0

    def test_the_build_and_the_read_run_inside_the_slot_the_comparison_is_given(self) -> None:
        alert = self._alert(detector=None)
        slots_held: list[bool] = []
        held_when_the_shadow_query_starts: list[bool] = []

        @contextmanager
        def query_slot() -> Iterator[None]:
            slots_held.append(True)
            try:
                yield
            finally:
                slots_held.pop()

        def runner(*args: Any, **kwargs: Any) -> Any:
            held_when_the_shadow_query_starts.append(bool(slots_held))
            return effective_trends_runner(*args, **kwargs)

        with self._enrolled(), patch(f"{_SHADOW}.effective_trends_runner", side_effect=runner):
            _platform_check(alert, query_slot)

        assert held_when_the_shadow_query_starts == [True]
        assert slots_held == []

    def test_attempt_cleanup_stops_a_running_shadow_insert_without_retrying_or_changing_the_live_verdict(self) -> None:
        alert = self._alert(detector=None)
        live = check_alert_for_insight(alert)
        team_id = self.team.pk
        attempt = f"{uuid4()}:1"
        requester = f"{QUERY_ID_PREFIX}{attempt}"
        inserts: list[str | None] = []

        def stop_when_running() -> None:
            def insert_running() -> bool:
                return bool(
                    sync_execute(
                        "SELECT count() FROM system.processes WHERE query_kind = 'Insert' AND position(query_id, %(id)s) > 0",
                        {"id": requester},
                    )[0][0]
                )

            wait_until(insert_running, timeout=10, message="the alert's tagged INSERT did not reach ClickHouse")
            stop_insight_queries(team_id, str(alert.pk), [attempt])

        def execute(sql: str, *args: Any, **kwargs: Any) -> Any:
            if not sql.lstrip().startswith("INSERT"):
                return sync_execute(sql, *args, **kwargs)
            inserts.append(get_query_tags().client_query_id)
            assert len(inserts) == 1
            with ThreadPoolExecutor(max_workers=1) as pool:
                cleanup = pool.submit(stop_when_running)
                try:
                    # A small test dataset would finish before cleanup could discover the INSERT.
                    return sync_execute(
                        "INSERT INTO FUNCTION null('number UInt64') SELECT number FROM numbers(100) "
                        "WHERE sleepEachRow(0.2) = 0 SETTINGS max_block_size = 1"
                    )
                finally:
                    cleanup.result(timeout=15)

        with (
            tags_context(team_id=team_id, client_query_id=requester),
            patch(
                "products.analytics_platform.backend.lazy_computation.lazy_computation_executor.sync_execute",
                side_effect=execute,
            ),
            patch(
                "posthog.clickhouse.cancel.default_client",
                side_effect=lambda **kwargs: default_client(**{**kwargs, "host": settings.CLICKHOUSE_HOST}),
            ),
        ):
            result, properties = self._shadowed_check(alert)

        assert result == live
        assert (properties["outcome"], properties["reason"]) == ("unavailable", "query_cancelled")
        (insert,) = inserts
        job_ids = PreaggregationJob.objects.filter(team_id=team_id).values_list("pk", flat=True)
        assert insert in {f"{job_id}_{requester}" for job_id in job_ids}

    def test_a_full_query_pool_skips_the_comparison(self) -> None:
        alert = self._alert(detector=None)

        def full_pool() -> AbstractContextManager[object]:
            raise QuerySlotFull()

        with self._enrolled(), patch(f"{_SHADOW}.posthoganalytics.capture") as capture:
            _platform_check(alert, full_pool)

        [properties] = _shadow_events(capture)
        assert (properties["outcome"], properties["reason"]) == ("unavailable", "no_query_slot")
        assert self._jobs() == 0

    def test_a_result_with_several_series_is_not_compared(self) -> None:
        count = {"kind": "EventsNode", "event": "signed_up", "math": "total"}
        alert = self._alert_on(
            {**_trends_query("day"), "series": [count, {**count, "event": "other"}]},
            {"type": "TrendsAlertConfig", "series_index": 1},
            detector=None,
            calculation_interval="daily",
        )

        _, properties = self._shadowed_check(alert)

        assert (properties["outcome"], properties["reason"]) == ("unavailable", "multiple_series")
        assert self._jobs() == 0

    @parameterized.expand(
        [
            ("query_of_a_stopped_attempt", CHQueryErrorQueryWasCancelled("killed", code=394), True, []),
            ("cancelled_activity", CancelledError(), True, []),
            (
                "query_killed_while_the_attempt_runs",
                CHQueryErrorQueryWasCancelled("killed", code=394),
                False,
                [("unavailable", "query_cancelled")],
            ),
        ]
    )
    def test_a_cancelled_shadow_query_stops_the_check_only_when_its_attempt_stops(
        self, _name: str, cancellation: Exception, attempt_stops: bool, recorded: list[tuple[str, str]]
    ) -> None:
        alert = self._alert(detector=_THRESHOLD_DETECTOR)
        stopped = False

        def cancelled(*args: Any, **kwargs: Any) -> Any:
            nonlocal stopped
            stopped = attempt_stops
            raise cancellation

        with (
            self._enrolled(),
            patch(f"{_SHADOW}.attempt_outlasts", side_effect=lambda seconds: not stopped),
            patch(f"{_SHADOW}.precomputed_series_values", side_effect=cancelled),
            patch(f"{_SHADOW}.posthoganalytics.capture") as capture,
            self.assertRaises(type(cancellation)) if attempt_stops else nullcontext(),
        ):
            _platform_check(alert)

        assert [(event["outcome"], event["reason"]) for event in _shadow_events(capture)] == recorded

    @parameterized.expand([("no_results", None, False), ("empty_results", [], True)])
    def test_an_empty_live_result_builds_nothing(self, _name: str, live: list | None, is_cached: bool) -> None:
        alert = self._alert(detector=None)

        with self._enrolled(), patch(f"{_SHADOW}.posthoganalytics.capture") as capture:
            with collecting_shadow_comparisons() as requested:
                compare_series_values_shadow(
                    alert,
                    TrendsQuery.model_validate(_trends_query("day")),
                    None,
                    InsightResult(result=live, last_refresh=None, cache_key=None, is_cached=is_cached, timezone=None),
                    alert_kind="threshold",
                )
            for comparison in requested:
                comparison.run(_query_slot)

        [properties] = _shadow_events(capture)
        assert (properties["outcome"], properties["reason"]) == ("unavailable", "no_live_result")
        assert properties["live_cached"] is is_cached
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
            checked = _platform_check(alert)

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
            checked = _platform_check(alert)

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
            _platform_check(alert)


class TestCompareClosedValues(SimpleTestCase):
    @parameterized.expand(
        [
            ("stored_values_agree", 2, "partial", 0.0),
            ("stored_values_differ", 3, "mismatch", 1.0),
        ]
    )
    def test_a_stored_day_missing_from_the_live_result_is_not_a_match(
        self, _name: str, stored: int, outcome: str, max_abs_difference: float
    ) -> None:
        precomputed = PrecomputedSeriesValues(values={datetime(2024, 1, 13): 5, datetime(2024, 1, 14): stored})
        live = [{"days": ["2024-01-14", "2024-01-15"], "data": [2, 3]}]

        comparison = compare_precomputed_values(precomputed, live)

        assert (
            comparison.outcome,
            comparison.buckets_compared,
            comparison.buckets_missing,
            comparison.max_abs_difference,
        ) == (outcome, 1, 1, max_abs_difference)
