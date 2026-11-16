import json
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast
from uuid import UUID

import pytest
import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import get_query_tags
from posthog.constants import AvailableFeature
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseClusterMemoryLimitExceeded
from posthog.models.scoping import team_scope
from posthog.models.user import User
from posthog.query_cache.single_flight import query_single_flight_skipped
from posthog.redis import get_client
from posthog.schema_enums import AlertCalculationInterval
from posthog.tasks.alerts.utils import (
    AlertEvaluationResult,
    InsightChartRenderFailed,
    RenderedInsightChart,
    next_check_time,
)
from posthog.temporal.ai.anomaly_investigation.workflow import _investigated_alert as load_investigated_alert
from posthog.temporal.alerts.admission import admit_evaluation_slots, inflight_alert_ids, release_evaluation_slot
from posthog.temporal.alerts.retry_policy import ALERT_EVALUATE_RETRY_POLICY

from products.alerts.backend.evaluation.contract import (
    CREATOR_LEFT_DISABLE_REASON,
    AlertDataUnavailableError,
    AlertExtractionError,
    AlertOwnerAccessError,
)
from products.alerts.backend.evaluation.dispatcher import PerSeriesEvaluation, SeriesEvaluation
from products.alerts.backend.judge.contract import (
    FORECAST_DETECTOR_PAUSED_ERROR_CODE,
    FORECAST_DETECTOR_UNAVAILABLE_MESSAGE,
    LLM_DETECTOR_PAUSED_ERROR_CODE,
    LLM_DETECTOR_UNAVAILABLE_ERROR_CODE,
    LLM_DETECTOR_UNAVAILABLE_MESSAGE,
    ForecastDetectorPausedError,
    LLMDetectorMisconfiguredError,
    LLMDetectorPausedError,
    LLMDetectorUnavailableError,
)
from products.alerts.backend.logic.alert_email import INSIGHT_ALERT_ERRORED_EVENT_ID
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, InvestigationStatus
from products.alerts.backend.models.investigation import InsightAlertInvestigation
from products.alerts.backend.platform_alert_wording import insight_alert_url
from products.alerts.backend.platform_chart_detail import CHART_PENDING_KEY, RenderedChart
from products.alerts.backend.platform_firing_signal import prepare_platform_firing_signals
from products.alerts.backend.platform_firing_signal_detail import FiringSignalRequest, requested_firing_signals
from products.alerts.backend.platform_investigation import claim_requested_investigations
from products.alerts.backend.platform_investigation_detail import SUPPRESSED_BY_AGENT_KEY, requested_investigation
from products.alerts.backend.platform_source_cycle import (
    CAPACITY_REJECTED,
    CHART_RENDER_INFLIGHT_KEY,
    INFLIGHT_KEY,
    MAX_BREACH_CHARS,
    MAX_DETECTOR_POINTS,
    MAX_RATIONALE_CHARS,
    QUERY_ID_PREFIX,
    QUERY_INFLIGHT_KEY,
    ChartRenderPoolFull,
    ChartRenderTimedOut,
    evaluate_insight_check,
    fail_insight_check,
    legacy_alerts_of,
    plan_insight_batch,
    readmit_retried_check,
    render_firing_chart,
    stop_insight_queries,
)
from products.alerts.backend.temporal.platform_evaluate import (
    AdmittedInsightCheck,
    InsightBatchPlanInputs,
    MetricsInvestigationsInputs,
    plan_platform_insight_checks_activity,
    run_platform_metrics_investigations_activity,
)
from products.alerts.backend.test.insight_alerts import create_insight_alert
from products.alerts_platform.backend.facade import (
    api as platform_facade,
    testing as platform_testing,
)
from products.alerts_platform.backend.facade.api import (
    create_alert_destinations,
    list_configurations,
    record_outcomes,
    slot_of,
)
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    AlertBatchKey,
    AlertDestinationData,
    AlertEventKind,
    DestinationType,
    Grouping,
    GroupingMode,
    IncidentAction,
    NewAlertDestination,
    PlatformAlertOutcome,
    PlatformCheckEvent,
    PlatformCheckEventPage,
    PlatformConfigurationSnapshot,
    SourceEvaluationInputs,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner, PlatformAlertState
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.signals.backend.facade.source_configs import AlertNamePatterns, SignalSourceConfigSnapshot

_MODULE = "products.alerts.backend.platform_source_cycle"
_FIRING_SIGNAL_MODULE = "products.alerts.backend.platform_firing_signal"
_EMITTER_MODULE = "posthog.temporal.alerts.alert_firing_signal"
# A Wednesday, so no weekend rule applies.
CUTOFF = datetime(2026, 9, 16, 10, tzinfo=UTC)


def _check_event(*, previous_state: str, state: str) -> PlatformCheckEvent:
    return PlatformCheckEvent(
        occurred_at=CUTOFF - timedelta(hours=1),
        evaluation_key="slot:earlier",
        previous_state=PlatformAlertState(previous_state),
        state=PlatformAlertState(state),
        value=None,
        condition={},
        query_duration_ms=None,
        error_message=None,
    )


_AGENT_ON: Final = {
    "detector_config": {"type": "zscore", "threshold": 0.95, "window": 30},
    "investigation_agent_enabled": True,
}


# Rows draw first, then alerts with no insight row, each oldest first.
_ROW_FIRST: Final = [("alert upper threshold", 100.0), ("sibling lower threshold", 5.0)]
_SIBLING_FIRST: Final = [("sibling lower threshold", 5.0), ("alert upper threshold", 100.0)]


class TestPlatformInsightEvaluation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        get_client().delete(INFLIGHT_KEY, QUERY_INFLIGHT_KEY, CHART_RENDER_INFLIGHT_KEY)
        self.addCleanup(get_client().delete, INFLIGHT_KEY, QUERY_INFLIGHT_KEY, CHART_RENDER_INFLIGHT_KEY)
        self.organization.available_product_features = [
            {"key": AvailableFeature.HIGH_FREQUENCY_ALERTS, "name": "High-frequency alerts"},
            {"key": AvailableFeature.REAL_TIME_ALERTS, "name": "Real-time alerts"},
        ]
        self.organization.save()

    def _alert(self, **overrides: Any) -> AlertConfiguration:
        # Production always writes an owner, and an alert with none counts as one whose owner was deleted.
        return create_insight_alert(
            self.team, **{"next_check_at": CUTOFF - timedelta(minutes=1), "created_by": self.user, **overrides}
        )

    def _copy(self, alert: AlertConfiguration | None, **overrides: Any) -> PlatformConfigurationSnapshot:
        with team_scope(self.team.id):
            return platform_testing.create_configuration(
                **{
                    "team_id": self.team.id,
                    "name": "alert",
                    "source_kind": SourceKind.INSIGHT,
                    "source_config": {
                        "insight_id": alert.insight_id,
                        SOURCE_CONDITION_KEY: {"detector": alert.detector_config},
                    }
                    if alert
                    else {},
                    "check_interval_minutes": 60 * 24,
                    "recurrence_unit": "day",
                    "next_check_at": CUTOFF - timedelta(minutes=1),
                    "legacy_configuration_id": alert.id if alert else None,
                    **overrides,
                }
            )

    def _native(self, alert: AlertConfiguration) -> PlatformConfigurationSnapshot:
        """A platform alert with the row's insight and threshold, and no insight row."""
        configuration = self._copy(
            alert,
            legacy_configuration_id=None,
            owner=PlatformAlertOwner.PLATFORM,
            destinations_owner=PlatformAlertOwner.PLATFORM,
            created_by=self.user,
            source_config={
                "insight_id": alert.insight_id,
                SOURCE_CONDITION_KEY: {
                    "comparison": {"type": "absolute_value"},
                    "threshold": {"type": "absolute", "bounds": {"upper": 100.0}},
                },
            },
        )
        alert.delete()
        return configuration

    def _evaluate_per_series(
        self,
        configuration: PlatformConfigurationSnapshot,
        values: dict[str, float] | list[tuple[str, float]],
        *,
        truncated: bool = False,
        breach: str = "above 100",
        error: Exception | None = None,
    ) -> PlatformAlertOutcome:
        slot = slot_of(configuration.next_check_at, CUTOFF)
        expires_at = time.time() + 3600
        assert plan_insight_batch(self.team.id, slot, CUTOFF, expires_at=expires_at) == (str(configuration.id),)
        # One label for every series, so a key taken from the label instead of the identity merges them.
        evaluated = PerSeriesEvaluation(
            series=tuple(
                SeriesEvaluation(
                    identity=identity,
                    label="browser",
                    result=AlertEvaluationResult(value=value, breaches=[breach] if value > 100 else []),
                )
                for identity, value in (values.items() if isinstance(values, dict) else values)
            ),
            truncated=truncated,
        )
        with patch(f"{_MODULE}.check_alert_per_series", return_value=evaluated, side_effect=error):
            evaluation = evaluate_insight_check(
                self.team.id, slot, CUTOFF, str(configuration.id), held_until=expires_at, evaluation_id="test"
            )
        assert evaluation is not None
        (outcome,) = evaluation.outcomes
        return outcome

    @parameterized.expand([("complete", False, "not_firing"), ("past_the_breakdown_limit", True, None)])
    def test_each_breakdown_value_fires_and_resolves_on_its_own(
        self, _name: str, truncated: bool, missing_state: str | None
    ) -> None:
        grouping = Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("breakdown",))
        configuration = self._copy(self._alert(), grouping=grouping.to_stored())

        fired = self._evaluate_per_series(configuration, {"Chrome": 150.0, "Safari": 40.0, "Firefox": 120.0})
        record_outcomes(self.team.id, (fired,), CUTOFF)
        assert {group.grouping_key: group.kind for group in fired.groups} == {
            "Chrome": AlertEventKind.FIRING,
            "Firefox": AlertEventKind.FIRING,
        }
        assert {group.source_detail["breaches"][0] for group in fired.groups} == {"above 100"}

        with team_scope(self.team.id):
            platform_testing.set_due_at(configuration.id, CUTOFF - timedelta(minutes=1))
        resolved = self._evaluate_per_series(configuration, {"Chrome": 150.0}, truncated=truncated)

        expected = {"Chrome": "firing"} | ({"Firefox": missing_state} if missing_state else {})
        assert {group.grouping_key: group.new_state for group in resolved.groups} == expected

    def test_a_wide_breakdown_firing_stays_inside_what_temporal_carries(self) -> None:
        # Every firing group repeats the card fields, so a field added per group multiplies by the
        # group limit. The whole outcome crosses an activity boundary that refuses ~2 MiB.
        grouping = Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("breakdown",))
        configuration = self._copy(self._alert(), grouping=grouping.to_stored())

        fired = self._evaluate_per_series(
            configuration, {f"value-{index}": 150.0 for index in range(120)}, breach="x" * 2000
        )

        assert len(fired.groups) > 1
        assert len(json.dumps([group.source_detail for group in fired.groups], default=str)) < 1_000_000
        # Trimming drops the repeated fields, never the group's own identity or its breaches.
        for group in fired.groups:
            assert group.source_detail["alert_id"]
            assert group.source_detail["breaches"]

    def test_a_breakdown_value_reported_twice_keeps_the_breach_of_the_row_that_fired(self) -> None:
        grouping = Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("breakdown",))
        configuration = self._copy(self._alert(), grouping=grouping.to_stored())

        fired = self._evaluate_per_series(configuration, [("Chrome", 150.0), ("Chrome", 40.0)], breach="x" * 2000)

        (group,) = fired.groups
        # The detail rides in the outcome Temporal carries, so a long breach is clipped.
        assert (group.kind, len(group.source_detail["breaches"][0])) == (AlertEventKind.FIRING, MAX_BREACH_CHARS)

    def test_a_muted_breakdown_value_tracks_its_firing_without_announcing_it(self) -> None:
        grouping = Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("breakdown",))
        configuration = self._copy(
            self._alert(), grouping=grouping.to_stored(), snooze_until=CUTOFF + timedelta(hours=1)
        )

        outcome = self._evaluate_per_series(configuration, {"Chrome": 150.0})

        assert [(group.kind, group.new_state, group.muted_notification) for group in outcome.groups] == [
            (AlertEventKind.CHECK, "firing", "fire")
        ]

    def _evaluate(
        self, configuration: PlatformConfigurationSnapshot, *, result: Any = None, uses_llm_detector: bool = False
    ) -> tuple[PlatformAlertOutcome | None, MagicMock]:
        slot = slot_of(configuration.next_check_at, CUTOFF)
        expires_at = time.time() + 3600
        assert plan_insight_batch(self.team.id, slot, CUTOFF, expires_at=expires_at) == (str(configuration.id),)
        side_effect = None if isinstance(result, AlertEvaluationResult) else result
        returned = result if isinstance(result, AlertEvaluationResult) else None
        with patch(f"{_MODULE}.check_alert_for_insight", side_effect=side_effect, return_value=returned) as query:
            evaluation = evaluate_insight_check(
                self.team.id,
                slot,
                CUTOFF,
                str(configuration.id),
                held_until=expires_at,
                evaluation_id="test",
                uses_llm_detector=uses_llm_detector,
            )
        self.deliveries = evaluation.deliveries if evaluation is not None else ()
        return (evaluation.outcomes[0] if evaluation is not None else None), query

    @parameterized.expand([("owner_taken_over_since_the_copy", True), ("not_yet_backfilled", False)])
    def test_the_check_runs_as_the_alerts_current_owner_and_the_copy_follows(
        self, _name: str, stale_creator: bool
    ) -> None:
        previous_owner = User.objects.create_and_join(self.organization, "previous-owner@example.com", None)
        configuration = self._copy(self._alert(), created_by_id=previous_owner.id if stale_creator else None)

        _, query = self._evaluate(configuration, result=AlertEvaluationResult(value=1.0, breaches=[]))

        with team_scope(self.team.id):
            (copy,) = list_configurations(
                team_id=self.team.id, source_kinds=[SourceKind.INSIGHT.value], limit=10, offset=0
            ).configurations
        assert (query.call_args.args[0].created_by, copy.created_by_id) == (self.user, self.user.id)

    @parameterized.expand(
        [
            ("source_owned", "source", False),
            ("platform_owned", "platform", True),
        ]
    )
    def test_a_firing_records_what_production_sends_beside_it(self, _name: str, owner: str, wants_chart: bool) -> None:
        alert = self._alert()
        configuration = self._copy(alert, owner=owner)
        expected = {
            "breaches": ["above 100"],
            "insight_name": alert.insight.name,
            "insight_short_id": alert.insight.short_id,
            "alert_id": str(alert.id),
            # Recorded at trigger time so the card stays a function of the transition.
            "metric_name": alert.insight.name,
            "timezone": self.team.timezone,
            "is_anomaly": False,
            "insight_interval": "day",
            "tags": [],
            "team_name": self.team.name,
            **({CHART_PENDING_KEY: str(alert.id)} if wants_chart else {}),
        }

        with patch(f"{_MODULE}.render_alert_insight_chart_or_raise") as render:
            outcome, _ = self._evaluate(
                configuration, result=AlertEvaluationResult(value=150.0, breaches=["above 100"])
            )

        assert outcome is not None
        assert outcome.groups[0].source_detail == expected
        # A render takes up to a minute and a half, so it never runs while the check holds its pool slot.
        render.assert_not_called()

    @parameterized.expand(
        [
            ("a_wrapped_query", {"kind": "InsightVizNode", "source": {"interval": "week"}}, "week"),
            # A `.get("source", default)` never replaces an explicit null, so this shape used to
            # raise inside the check — losing the firing over a label on its card.
            ("an_explicit_null_source", {"kind": "InsightVizNode", "source": None, "interval": "hour"}, "hour"),
            ("a_source_that_is_not_a_query", {"source": "trends", "interval": "month"}, "month"),
        ]
    )
    def test_a_firing_records_the_interval_of_any_stored_query_shape(
        self, _name: str, query: dict[str, Any], interval: str
    ) -> None:
        alert = self._alert()
        alert.insight.query = query
        alert.insight.save(update_fields=["query"])
        configuration = self._copy(alert)

        outcome, _ = self._evaluate(configuration, result=AlertEvaluationResult(value=150.0, breaches=["above 100"]))

        assert outcome is not None
        assert outcome.groups[0].source_detail["insight_interval"] == interval

    @override_settings(ALERTS_PLATFORM_INSIGHT_MAX_INFLIGHT_CHART_RENDERS=1)
    def test_a_chart_render_holds_a_render_slot_only_while_it_runs(self) -> None:
        alert = self._alert()
        held_until = time.time() + 60

        with patch(
            f"{_MODULE}.render_alert_insight_chart_or_raise",
            return_value=RenderedInsightChart(asset_id=7, render_user_id=3),
        ) as render:
            # Back to back on a pool of one, so the second render needs the slot the first gave back.
            for _ in range(2):
                assert render_firing_chart(self.team.id, str(alert.id), held_until=held_until) == RenderedChart(
                    asset_id=7, render_user_id=3
                )
            admit_evaluation_slots(["another-render"], limit=1, expires_at=held_until, key=CHART_RENDER_INFLIGHT_KEY)
            with pytest.raises(ChartRenderPoolFull):
                render_firing_chart(self.team.id, str(alert.id), held_until=held_until)

        assert render.call_count == 2

    @parameterized.expand(
        [("failed_quickly", timedelta(seconds=90), False), ("used_the_whole_limit", timedelta(0), True)]
    )
    def test_a_render_that_fails_at_the_export_limit_timed_out(
        self, _name: str, limit: timedelta, timed_out: bool
    ) -> None:
        alert = self._alert()

        with (
            patch(f"{_MODULE}.render_alert_insight_chart_or_raise", side_effect=InsightChartRenderFailed("no content")),
            patch(f"{_MODULE}.CHART_RENDER_TIMEOUT", limit),
        ):
            with pytest.raises(ChartRenderTimedOut if timed_out else InsightChartRenderFailed):
                render_firing_chart(self.team.id, str(alert.id), held_until=time.time() + 60)

        # The slot is free either way, so the next firing's render is not held back.
        assert inflight_alert_ids(CHART_RENDER_INFLIGHT_KEY) == set()

    @parameterized.expand(
        [
            ("a_row_with_a_slack_function", "row", "hog_function", [_ROW_FIRST]),
            # Its row's threshold drifted from the copy's, which the platform owns.
            (
                "a_moved_alert_with_a_slack_function",
                "copy",
                "hog_function",
                [[("sibling lower threshold", 5.0), ("alert upper threshold", 200.0)]],
            ),
            ("a_native_alert_with_a_slack_function", "native", "hog_function", [_SIBLING_FIRST]),
            ("a_native_alert_with_a_platform_slack_destination", "native", "platform", [_SIBLING_FIRST]),
            ("a_native_alert_without_slack", "native", None, []),
        ]
    )
    def test_a_firing_chart_draws_the_threshold_of_every_enabled_alert_on_the_insight(
        self, _name: str, kind: str, slack: str | None, rendered_lines: list[list[tuple[str, float]]]
    ) -> None:
        alert = self._alert()
        for name, enabled in (("sibling", True), ("disabled", False)):
            self._copy(
                alert,
                name=name,
                enabled=enabled,
                legacy_configuration_id=None,
                owner=PlatformAlertOwner.PLATFORM,
                destinations_owner=PlatformAlertOwner.PLATFORM,
                source_config={
                    "insight_id": alert.insight_id,
                    SOURCE_CONDITION_KEY: {
                        "comparison": {"type": "absolute_value"},
                        "threshold": {"type": "absolute", "bounds": {"lower": 5.0}},
                    },
                },
            )
        if kind == "copy":
            self._copy(
                alert,
                owner=PlatformAlertOwner.PLATFORM,
                source_config={
                    "insight_id": alert.insight_id,
                    SOURCE_CONDITION_KEY: {
                        "comparison": {"type": "absolute_value"},
                        "threshold": {"type": "absolute", "bounds": {"upper": 200.0}},
                    },
                },
            )
            AlertConfiguration.objects.filter(id=alert.id).update(owner=PlatformAlertOwner.PLATFORM)
        chart_alert_id = self._native(alert).id if kind == "native" else alert.id
        if slack == "hog_function":
            HogFunction.objects.create(
                team=self.team,
                type="internal_destination",
                name="Slack",
                template_id="template-slack",
                hog="return event",
                enabled=True,
                filters={
                    "source": "internal-events",
                    "events": [{"id": "$insight_alert_firing", "type": "events"}],
                    "properties": [
                        {"key": "alert_id", "value": str(chart_alert_id), "operator": "exact", "type": "event"}
                    ],
                },
            )
        elif slack == "platform":
            create_alert_destinations(
                team_id=self.team.id,
                configuration_id=chart_alert_id,
                destinations=(
                    NewAlertDestination(
                        data=cast(
                            AlertDestinationData,
                            {"type": DestinationType.SLACK, "slack_workspace_id": 1, "slack_channel_id": "C-1"},
                        ),
                        event_kinds=(AlertEventKind.FIRING,),
                    ),
                ),
            )

        with patch(
            "posthog.tasks.alerts.utils.exports.render_png_export", return_value=(MagicMock(id=7), b"png")
        ) as render:
            chart = render_firing_chart(self.team.id, str(chart_alert_id), held_until=time.time() + 60)

        assert chart == (RenderedChart(asset_id=7, render_user_id=self.user.id) if rendered_lines else None)
        assert [
            [(line["label"], line["value"]) for line in call.kwargs["reference_lines"]]
            for call in render.call_args_list
        ] == rendered_lines

    @override_settings(ALERTS_PLATFORM_INSIGHT_MAX_INFLIGHT_EVALUATIONS=1)
    def test_a_check_holds_a_clickhouse_slot_only_while_its_query_runs(self) -> None:
        configuration = self._copy(self._alert())
        slot = slot_of(configuration.next_check_at, CUTOFF)
        expires_at = time.time() + 3600
        (admitted,) = plan_insight_batch(self.team.id, slot, CUTOFF, expires_at=expires_at)
        other_query_until = time.time() + 60
        admit_evaluation_slots(["other-query"], limit=1, expires_at=other_query_until, key=QUERY_INFLIGHT_KEY)
        held_during_query: list[set[str]] = []

        def query(
            *args: Any, query_slot: Callable[[], AbstractContextManager[object]], **kwargs: Any
        ) -> AlertEvaluationResult:
            with query_slot():
                held_during_query.append(inflight_alert_ids(QUERY_INFLIGHT_KEY))
            return AlertEvaluationResult(value=1.0, breaches=[])

        with (
            patch(f"{_MODULE}.check_alert_for_insight", side_effect=query),
            patch(f"{_MODULE}._QUERY_LIMIT.retry_timeout", 0),
        ):
            starved = evaluate_insight_check(
                self.team.id, slot, CUTOFF, admitted, held_until=expires_at, evaluation_id="test"
            )
            release_evaluation_slot("other-query", held_until=other_query_until, key=QUERY_INFLIGHT_KEY)
            evaluation = evaluate_insight_check(
                self.team.id, slot, CUTOFF, admitted, held_until=expires_at, evaluation_id="test"
            )

        assert starved is None
        assert evaluation is not None and evaluation.outcomes[0].failure is None
        assert held_during_query == [{"test:1"}]
        assert inflight_alert_ids(QUERY_INFLIGHT_KEY) == set()

    @parameterized.expand(
        [
            (
                "quiet_ai_check",
                {"type": "llm"},
                AlertEvaluationResult(
                    value=50.0,
                    breaches=[],
                    interval="day",
                    triggered_metadata={"detector_type": "llm", "rationale": "x" * 5000, "kind": "none"},
                ),
                {
                    "interval": "day",
                    "triggered_metadata": {
                        "detector_type": "llm",
                        "rationale": "x" * (MAX_RATIONALE_CHARS - 1) + "…",
                        "kind": "none",
                    },
                },
            ),
            (
                "firing_statistical_check",
                {"type": "zscore"},
                AlertEvaluationResult(
                    value=150.0,
                    breaches=["Anomaly detected"],
                    anomaly_scores=[0.1] * 30,
                    triggered_points=[89],
                    triggered_dates=["2026-09-15"],
                    interval="day",
                    triggered_metadata={"detector_type": "zscore", "series_index": 0},
                ),
                {
                    "breaches": ["Anomaly detected"],
                    "anomaly_scores": [0.1] * MAX_DETECTOR_POINTS,
                    "triggered_points": [89],
                    "triggered_dates": ["2026-09-15"],
                    "interval": "day",
                    "triggered_metadata": {"detector_type": "zscore", "series_index": 0},
                },
            ),
        ]
    )
    def test_every_detector_check_records_what_production_keeps_on_its_check(
        self, _name: str, detector_config: dict[str, Any], result: AlertEvaluationResult, expected: dict[str, Any]
    ) -> None:
        alert = self._alert(detector_config=detector_config)
        configuration = self._copy(alert)

        outcome, _ = self._evaluate(configuration, result=result, uses_llm_detector=detector_config["type"] == "llm")

        assert outcome is not None
        assert {key: outcome.groups[0].source_detail.get(key) for key in expected} == expected

    @parameterized.expand(
        [
            ("renamed", {"name": "Signups dropped"}, ("Signups dropped", 60 * 24, "day", None)),
            # A skipped check advances by the copy's schedule, so it must refresh the copy first.
            (
                "renamed_while_off",
                {"name": "Signups dropped", "enabled": False},
                ("Signups dropped", 60 * 24, "day", None),
            ),
            (
                "weekly",
                {"calculation_interval": AlertCalculationInterval.WEEKLY.value},
                ("alert", 60 * 24 * 7, "week", None),
            ),
            ("started_later", {"schedule_start_time": "09:30"}, ("alert", 60 * 24, "day", "09:30")),
            # A stored anchor that cannot advance would fail every outcome recorded beside it.
            ("unreadable_start_time", {"schedule_start_time": "25:99"}, ("alert", 60 * 24, "day", None)),
        ]
    )
    def test_a_check_brings_its_copy_up_to_date_with_the_alert(
        self, _name: str, edits: dict[str, Any], expected: tuple[str, int, str, str | None]
    ) -> None:
        alert = self._alert(**edits)
        configuration = self._copy(alert)

        self._evaluate(configuration, result=AlertEvaluationResult(value=50.0, breaches=[]))

        with team_scope(self.team.id):
            (copy,) = list_configurations(
                team_id=self.team.id, source_kinds=[SourceKind.INSIGHT.value], limit=10, offset=0
            ).configurations
        assert (copy.name, copy.check_interval_minutes, copy.recurrence_unit, copy.anchor_time) == expected

    @parameterized.expand([("threshold", {}), ("detector", {"detector_config": {"type": "zscore"}})])
    def test_a_breach_fires_on_the_platform_and_leaves_the_production_alert_alone(
        self, _name: str, alert_overrides: dict[str, Any]
    ) -> None:
        alert = self._alert(**alert_overrides)
        before = AlertConfiguration.objects.values("state", "next_check_at", "last_checked_at").get(id=alert.id)
        configuration = self._copy(alert)

        skipped_during_query: list[bool] = []

        def query(*args: Any, **kwargs: Any) -> AlertEvaluationResult:
            skipped_during_query.append(query_single_flight_skipped())
            return AlertEvaluationResult(value=150.0, breaches=["above 100"])

        outcome, _ = self._evaluate(configuration, result=query)
        assert outcome is not None
        assert get_query_tags().ch_user == ClickHouseUser.ALERTS_PLATFORM_INSIGHT
        assert skipped_during_query == [True]
        record_outcomes(self.team.id, (outcome,), CUTOFF)

        assert (outcome.groups[0].kind, outcome.groups[0].value, outcome.evaluation_key) == (
            AlertEventKind.FIRING,
            150.0,
            f"slot:{slot_of(configuration.next_check_at, CUTOFF)}",
        )
        with team_scope(self.team.id):
            platform_alert = platform_testing.alert_for(configuration.id)
        assert platform_alert is not None and platform_alert.state == "firing"
        assert AlertConfiguration.objects.values("state", "next_check_at", "last_checked_at").get(id=alert.id) == before
        assert not AlertCheck.objects.filter(alert_configuration=alert).exists()

    @parameterized.expand(
        [
            ("every_15_minutes", AlertCalculationInterval.EVERY_15_MINUTES, 15, None, None, None),
            ("hourly", AlertCalculationInterval.HOURLY, 60, None, None, None),
            ("daily", AlertCalculationInterval.DAILY, 60 * 24, "day", None, None),
            ("weekly", AlertCalculationInterval.WEEKLY, 60 * 24 * 7, "week", None, None),
            # The next local hour is quiet, so the check moves to the window's end plus its offset.
            ("hourly_quiet_hours", AlertCalculationInterval.HOURLY, 60, None, ("16:00", "17:00"), None),
            ("daily_quiet_hours", AlertCalculationInterval.DAILY, 60 * 24, "day", ("00:30", "02:00"), None),
            ("hourly_start_time", AlertCalculationInterval.HOURLY, 60, None, None, "09:20"),
            # Real time steps from the previous due time, seconds and all, rather than from a grid.
            ("real_time", AlertCalculationInterval.REAL_TIME, 2, None, None, None, timedelta(seconds=90)),
            ("real_time_quiet_hours", AlertCalculationInterval.REAL_TIME, 2, None, ("15:31", "16:30"), None),
            ("real_time_start_time", AlertCalculationInterval.REAL_TIME, 2, None, None, "09:20", timedelta(seconds=90)),
        ]
    )
    def test_a_copy_is_next_due_when_the_production_alert_is(
        self,
        _name: str,
        interval: AlertCalculationInterval,
        minutes: int,
        unit: str | None,
        quiet: tuple[str, str] | None,
        start_time: str | None,
        overdue: timedelta = timedelta(minutes=1),
    ) -> None:
        # A half-hour timezone, where the local hour starts at :30 UTC.
        self.team.timezone = "Asia/Kolkata"
        self.team.save()
        restriction = {"blocked_windows": [{"start": quiet[0], "end": quiet[1]}]} if quiet else None
        alert = self._alert(
            calculation_interval=interval,
            schedule_restriction=restriction,
            schedule_start_time=start_time,
            next_check_at=CUTOFF - overdue,
        )
        configuration = self._copy(
            alert,
            check_interval_minutes=minutes,
            recurrence_unit=unit,
            schedule_restriction=restriction,
            anchor_time=start_time,
            next_check_at=CUTOFF - overdue,
        )

        with time_machine.travel(CUTOFF, tick=False):
            outcome, _ = self._evaluate(configuration, result=AlertEvaluationResult(value=1.0, breaches=[]))
            assert outcome is not None
            record_outcomes(self.team.id, (outcome,), CUTOFF)
            expected = next_check_time(alert)

        with team_scope(self.team.id):
            assert platform_testing.configuration(configuration.id).next_check_at == expected

    @parameterized.expand(
        [
            # name, was_firing, owned, paged through, breaks, (incident_actions, sends_messages) or no delivery
            ("source_owned", False, False, None, False, None),
            ("platform_owned", False, True, None, False, ({}, True)),
            ("platform_owned_resolve", True, True, None, False, None),
            ("paged_firing", False, True, "hog_function", False, ({"": IncidentAction.TRIGGER}, True)),
            ("paged_resolve", True, True, "hog_function", False, ({"": IncidentAction.RESOLVE}, False)),
            ("paged_firing_that_breaks", True, True, "hog_function", True, ({}, True)),
            ("paged_but_source_owned", False, False, "hog_function", False, None),
            ("paged_firing_with_no_row", False, True, "platform", False, ({"": IncidentAction.TRIGGER}, True)),
            ("paged_resolve_with_no_row", True, True, "platform", False, ({"": IncidentAction.RESOLVE}, False)),
        ]
    )
    def test_only_a_platform_owned_firing_failure_or_incident_edge_asks_for_a_delivery(
        self,
        _name: str,
        was_firing: bool,
        owned: bool,
        paged: str | None,
        breaks: bool,
        delivered: tuple[dict[str, IncidentAction], bool] | None,
    ) -> None:
        alert = self._alert()
        alert_url = insight_alert_url(self.team.id, alert.insight.short_id, str(alert.id))
        if paged == "platform":
            configuration = self._native(alert)
            alert_url = insight_alert_url(self.team.id, alert.insight.short_id, str(configuration.id))
            create_alert_destinations(
                team_id=self.team.id,
                configuration_id=configuration.id,
                destinations=(
                    NewAlertDestination(
                        data=cast(
                            AlertDestinationData,
                            {"type": DestinationType.PAGERDUTY, "pagerduty_routing_key": "a" * 32},
                        ),
                        event_kinds=(AlertEventKind.FIRING,),
                    ),
                ),
            )
        else:
            configuration = self._copy(alert, **({"owner": PlatformAlertOwner.PLATFORM} if owned else {}))
        if paged == "hog_function":
            HogFunction.objects.create(
                team=self.team,
                type="internal_destination",
                name="PagerDuty",
                template_id="template-pagerduty",
                hog="return event",
                enabled=True,
                filters={
                    "source": "internal-events",
                    "events": [{"id": "$insight_alert_incident_closed", "type": "events"}],
                    "properties": [{"key": "alert_id", "value": str(alert.id), "operator": "exact", "type": "event"}],
                },
            )
        if was_firing:
            fired, _ = self._evaluate(configuration, result=AlertEvaluationResult(value=150.0, breaches=["above 100"]))
            assert fired is not None
            record_outcomes(self.team.id, (fired,), CUTOFF)
            with team_scope(self.team.id):
                platform_testing.set_due_at(configuration.id, CUTOFF - timedelta(minutes=1))

        self._evaluate(
            configuration,
            result=AlertExtractionError("bad query shape")
            if breaks
            else AlertEvaluationResult(value=50.0, breaches=[] if was_firing else ["above 100"]),
        )

        expected = (
            [
                (
                    str(configuration.id),
                    str(configuration.id if paged == "platform" else alert.id),
                    {"firing": "$insight_alert_firing", "errored": INSIGHT_ALERT_ERRORED_EVENT_ID},
                    owned,
                    *delivered,
                )
            ]
            if delivered is not None
            else []
        )
        assert [
            (
                delivery.configuration_id,
                delivery.destination_alert_id,
                delivery.event_ids_by_kind,
                delivery.owned_by_platform,
                delivery.incident_actions,
                delivery.sends_messages,
            )
            for delivery in self.deliveries
        ] == expected
        # A native message links to the alert on its insight, where the insight stack's messages link.
        assert all(delivery.source_alert_url == alert_url for delivery in self.deliveries)

    @parameterized.expand(
        [
            ("disabled", {"enabled": False}, None, "not_firing"),
            ("snoozed", {"snoozed_until": CUTOFF + timedelta(hours=1)}, None, "snoozed"),
            ("switched_to_ai_after_its_copy", {}, {"type": "llm"}, "not_firing"),
        ]
    )
    def test_a_check_production_would_not_run_is_recorded_without_a_query(
        self, _name: str, overrides: dict[str, Any], detector_after_copy: dict[str, str] | None, state: str
    ) -> None:
        alert = self._alert(**overrides)
        configuration = self._copy(alert)
        if detector_after_copy is not None:
            alert.detector_config = detector_after_copy
            alert.save()

        outcome, query = self._evaluate(configuration, uses_llm_detector=detector_after_copy is not None)

        query.assert_not_called()
        assert outcome is not None
        assert (outcome.groups[0].kind, outcome.groups[0].new_state, outcome.disable) == (
            AlertEventKind.CHECK,
            state,
            detector_after_copy is not None,
        )

    @parameterized.expand(
        [
            ("ai_detector_on_the_default_worker", {"detector_config": {"type": "llm"}}, False),
            ("threshold_on_the_ai_worker", {}, True),
        ]
    )
    def test_a_check_routed_for_another_detector_stays_due_without_a_query(
        self, _name: str, overrides: dict[str, Any], uses_llm_detector: bool
    ) -> None:
        outcome, query = self._evaluate(self._copy(self._alert(**overrides)), uses_llm_detector=uses_llm_detector)

        query.assert_not_called()
        assert outcome is None

    @parameterized.expand(
        [
            ("copy_whose_production_alert_is_gone", {"legacy_configuration_id": UUID(int=404)}),
            ("alert_whose_insight_is_gone", {"source_config": {"insight_id": 0}}),
            ("alert_whose_insight_was_deleted", None),
        ]
    )
    def test_an_alert_with_nothing_left_to_check_is_disabled(
        self, _name: str, overrides: dict[str, Any] | None
    ) -> None:
        if overrides is None:
            insight = self._alert().insight
            insight.deleted = True
            insight.save()
            overrides = {"source_config": {"insight_id": insight.id}}
        outcome, query = self._evaluate(self._copy(None, **overrides))

        query.assert_not_called()
        assert outcome is not None and outcome.disable

    def test_an_alert_insight_keeps_no_row_for_is_checked_and_delivered_under_its_own_id(self) -> None:
        alert = self._alert(evaluation_delay_intervals=1)
        insight = alert.insight
        assert alert.threshold is not None
        threshold = alert.threshold.configuration
        configuration = self._copy(
            None,
            owner=PlatformAlertOwner.PLATFORM,
            created_by_id=self.user.id,
            source_config={
                "insight_id": insight.id,
                SOURCE_CONDITION_KEY: {"threshold": threshold, "comparison": alert.condition, "detector": None},
                "config": alert.config,
                "skip_weekend": False,
                "evaluation_delay_intervals": 1,
            },
        )
        alert.delete()
        slot = slot_of(configuration.next_check_at, CUTOFF)
        planned = legacy_alerts_of(self.team.id, slot, CUTOFF, [str(configuration.id)])[str(configuration.id)]
        assert (planned.calculation_interval, planned.platform_owned) == (AlertCalculationInterval.DAILY, True)

        outcome, query = self._evaluate(
            configuration, result=AlertEvaluationResult(value=150.0, breaches=["above 100"])
        )

        (evaluated,) = query.call_args.args
        assert (
            evaluated.id,
            evaluated.insight_id,
            evaluated.threshold.configuration,
            evaluated.config,
            evaluated.evaluation_delay_intervals,
            evaluated.created_by_id,
        ) == (configuration.id, insight.id, threshold, alert.config, 1, self.user.id)
        assert outcome is not None
        assert (outcome.groups[0].kind, outcome.disable) == (AlertEventKind.FIRING, False)
        assert [(delivery.destination_alert_id, delivery.source_alert_url) for delivery in self.deliveries] == [
            (str(configuration.id), insight_alert_url(self.team.id, insight.short_id, str(configuration.id)))
        ]
        assert not AlertConfiguration.objects.filter(team=self.team).exists()

    @parameterized.expand(
        [
            ("too_many_queries", ClickHouseAtCapacity(), None, ALERT_EVALUATE_RETRY_POLICY.maximum_attempts),
            (
                "cluster_memory_full",
                ClickHouseClusterMemoryLimitExceeded(),
                None,
                ALERT_EVALUATE_RETRY_POLICY.maximum_attempts,
            ),
            ("attempt_out_of_time", ClickHouseAtCapacity(), "start_to_close", 1),
            ("check_out_of_time", ClickHouseAtCapacity(), "schedule_to_close", 1),
        ]
    )
    def test_a_check_clickhouse_refuses_on_every_try_leaves_the_alert_as_it_was(
        self, _name: str, error: Exception, budget_spent: str | None, tries: int
    ) -> None:
        configuration = self._copy(self._alert())
        with patch(f"{_MODULE}.time.sleep"):
            if budget_spent is None:
                outcome, query = self._evaluate(configuration, result=error)
            else:
                now = datetime.now(UTC)
                spent = timedelta(minutes=13)
                environment = ActivityEnvironment()
                # A later attempt with its own start-to-close left, inside a schedule-to-close that ran out, or the reverse.
                environment.info = replace(
                    environment.info,
                    attempt=2,
                    scheduled_time=now - spent if budget_spent == "schedule_to_close" else now,
                    schedule_to_close_timeout=spent,
                    current_attempt_scheduled_time=now - spent if budget_spent == "start_to_close" else now,
                    start_to_close_timeout=timedelta(minutes=12),
                )
                outcome, query = environment.run(lambda: self._evaluate(configuration, result=error))

        assert outcome is not None
        assert (outcome.groups[0].kind, outcome.groups[0].new_state, outcome.error_message, outcome.disable) == (
            AlertEventKind.CHECK,
            "not_firing",
            CAPACITY_REJECTED,
            False,
        )
        assert query.call_count == tries

    def test_a_check_clickhouse_refuses_once_records_the_retried_query_verdict(self) -> None:
        with patch(f"{_MODULE}.time.sleep"):
            outcome, query = self._evaluate(
                self._copy(self._alert()),
                result=[ClickHouseAtCapacity(), AlertEvaluationResult(value=150.0, breaches=["above 100"])],
            )

        assert outcome is not None
        assert (outcome.groups[0].new_state, outcome.error_message, query.call_count) == ("firing", None, 2)

    def test_a_cadence_the_plan_no_longer_includes_errors_and_is_disabled(self) -> None:
        self.organization.available_product_features = []
        self.organization.save()

        outcome, query = self._evaluate(
            self._copy(self._alert(calculation_interval=AlertCalculationInterval.EVERY_15_MINUTES.value)),
            result=AlertEvaluationResult(value=1.0, breaches=[]),
        )

        assert outcome is not None and outcome.failure is not None
        assert (outcome.failure.kind, outcome.disable, query.called) == (AlertEventKind.ERRORED, True, False)

    @parameterized.expand(
        [
            ("bad_query_shape", AlertExtractionError("bad query shape")),
            ("ai_detector_without_a_creator", LLMDetectorMisconfiguredError("no creator")),
            ("owner_left_or_lost_access", AlertOwnerAccessError(CREATOR_LEFT_DISABLE_REASON)),
        ]
    )
    def test_an_alert_production_cannot_evaluate_as_configured_errors_and_is_disabled(
        self, _name: str, error: Exception
    ) -> None:
        outcome, _ = self._evaluate(self._copy(self._alert()), result=error)

        assert outcome is not None
        assert outcome.failure is not None and outcome.groups == ()
        assert (outcome.failure.kind, outcome.failure.new_state, outcome.disable) == (
            AlertEventKind.ERRORED,
            "errored",
            True,
        )
        # The error message names and links the insight, as a firing's does.
        assert set(outcome.failure.source_detail) == {"insight_name", "insight_short_id"}

    @parameterized.expand(
        [
            ("ai", {"type": "llm"}, LLMDetectorPausedError, LLM_DETECTOR_PAUSED_ERROR_CODE),
            ("forecast", {"type": "forecast"}, ForecastDetectorPausedError, FORECAST_DETECTOR_PAUSED_ERROR_CODE),
        ]
    )
    def test_a_paused_gateway_detector_errors_and_stays_enabled(
        self, _name: str, detector_config: dict, paused_error: type[LLMDetectorPausedError], code: str
    ) -> None:
        outcome, _ = self._evaluate(
            self._copy(self._alert(detector_config=detector_config)),
            result=paused_error("consent withdrawn"),
            uses_llm_detector=True,
        )

        assert outcome is not None and outcome.failure is not None
        assert (outcome.failure.kind, outcome.error_message, outcome.disable) == (
            AlertEventKind.ERRORED,
            "consent withdrawn",
            False,
        )
        assert outcome.failure.source_detail["error_code"] == code

    @parameterized.expand([("single", False), ("breakdown", True)])
    def test_a_check_without_enough_data_errors_and_stays_enabled(self, _name: str, breakdown: bool) -> None:
        error = AlertDataUnavailableError("not enough rows")
        outcome: PlatformAlertOutcome | None
        if breakdown:
            grouping = Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("breakdown",))
            outcome = self._evaluate_per_series(
                self._copy(self._alert(), grouping=grouping.to_stored()), {}, error=error
            )
        else:
            outcome, _ = self._evaluate(self._copy(self._alert()), result=error)

        assert outcome is not None and outcome.failure is not None
        assert (outcome.failure.kind, outcome.error_message, outcome.disable) == (
            AlertEventKind.ERRORED,
            "not enough rows",
            False,
        )

    @parameterized.expand([("retried", False), ("last_attempt", True)])
    def test_an_ai_detector_without_a_verdict_is_retried_and_only_its_last_attempt_records_an_error(
        self, _name: str, final_attempt: bool
    ) -> None:
        configuration = self._copy(self._alert(detector_config={"type": "llm"}))
        slot = slot_of(configuration.next_check_at, CUTOFF)
        expires_at = time.time() + 3600
        plan_insight_batch(self.team.id, slot, CUTOFF, expires_at=expires_at)

        with patch(f"{_MODULE}.check_alert_for_insight", side_effect=LLMDetectorUnavailableError("timed out")):
            if not final_attempt:
                with pytest.raises(LLMDetectorUnavailableError):
                    evaluate_insight_check(
                        self.team.id,
                        slot,
                        CUTOFF,
                        str(configuration.id),
                        held_until=expires_at,
                        evaluation_id="test",
                        final_attempt=False,
                        uses_llm_detector=True,
                    )
                # The retry still holds the slot, so the pool cannot hand it to another check.
                assert inflight_alert_ids(INFLIGHT_KEY) == {str(configuration.id)}
                return
            evaluation = evaluate_insight_check(
                self.team.id,
                slot,
                CUTOFF,
                str(configuration.id),
                held_until=expires_at,
                evaluation_id="test",
                uses_llm_detector=True,
            )

        assert evaluation is not None
        (outcome,) = evaluation.outcomes
        assert outcome.failure is not None
        assert (outcome.failure.kind, outcome.error_message, outcome.disable) == (
            AlertEventKind.ERRORED,
            LLM_DETECTOR_UNAVAILABLE_MESSAGE,
            False,
        )
        # History shows this reason by its code, as it does for the alert's own checks.
        assert outcome.failure.source_detail["error_code"] == LLM_DETECTOR_UNAVAILABLE_ERROR_CODE

    @parameterized.expand(
        [
            ("enabled", True, None, (AlertEventKind.ERRORED, "errored", "activity timed out", False, 1)),
            # The raw transport error is not the owner's configuration.
            (
                "judge_unreachable",
                True,
                "LLMDetectorUnavailableError",
                (AlertEventKind.ERRORED, "errored", LLM_DETECTOR_UNAVAILABLE_MESSAGE, False, 1),
            ),
            (
                "forecast_unreachable",
                True,
                "ForecastDetectorUnavailableError",
                (AlertEventKind.ERRORED, "errored", FORECAST_DETECTOR_UNAVAILABLE_MESSAGE, False, 1),
            ),
            # As production: switching an alert off mid-check is not a failure of the alert.
            ("switched_off", False, None, None),
        ]
    )
    def test_a_check_whose_every_attempt_failed_records_an_error(
        self,
        _name: str,
        enabled: bool,
        error_type: str | None,
        expected: tuple[AlertEventKind, str, str, bool, int] | None,
    ) -> None:
        configuration = self._copy(self._alert(enabled=enabled), owner=PlatformAlertOwner.PLATFORM)

        evaluation = fail_insight_check(
            self.team.id,
            slot_of(configuration.next_check_at, CUTOFF),
            CUTOFF,
            str(configuration.id),
            error_message="activity timed out",
            error_type=error_type,
        )

        actual = None
        if evaluation is not None:
            (outcome,) = evaluation.outcomes
            assert outcome.failure is not None
            actual = (
                outcome.failure.kind,
                outcome.failure.new_state,
                outcome.error_message,
                outcome.disable,
                len(evaluation.deliveries),
            )
        assert actual == expected

    def test_a_failed_checks_queries_are_stopped_even_when_one_stop_fails(self) -> None:
        with patch(
            "posthog.clickhouse.cancel.cancel_query_on_cluster", side_effect=[TimeoutError("socket timed out"), None]
        ) as cancel:
            stop_insight_queries(self.team.id, "configuration", ("run:1:1", "run:1:2"))

        # A timed-out attempt's thread can still run its query, which nothing else stops.
        assert [call.args for call in cancel.call_args_list] == [
            (self.team.id, f"{QUERY_ID_PREFIX}run:1:1"),
            (self.team.id, f"{QUERY_ID_PREFIX}run:1:2"),
        ]

    @override_settings(ALERTS_PLATFORM_INSIGHT_MAX_INFLIGHT_CHECKS=1)
    def test_a_retry_stops_the_timed_out_query_and_runs_only_inside_the_pool(self) -> None:
        held = self._copy(self._alert(), id=UUID(int=1))
        waiting = self._copy(self._alert(), id=UUID(int=2))
        slot = slot_of(held.next_check_at, CUTOFF)
        expires_at = time.time() + 3600
        assert plan_insight_batch(self.team.id, slot, CUTOFF, expires_at=expires_at) == (str(held.id),)
        admit_evaluation_slots(["run:1:1"], limit=1, expires_at=expires_at, key=QUERY_INFLIGHT_KEY)

        with patch("posthog.clickhouse.cancel.cancel_query_on_cluster") as cancel:
            retried = readmit_retried_check(
                self.team.id, str(held.id), previous_query_id="run:1:1", held_until=expires_at, attempt=2
            )
            # The timed-out attempt's thread finishes late and releases the slot it took.
            release_evaluation_slot(str(held.id), held_until=expires_at, key=INFLIGHT_KEY)
            over_the_limit = readmit_retried_check(
                self.team.id, str(waiting.id), previous_query_id="run:2:1", held_until=expires_at, attempt=2
            )

        assert retried is not None and over_the_limit is None
        assert inflight_alert_ids(INFLIGHT_KEY) == {str(held.id)}
        # The kill may not have landed, so the timed-out query stays counted until its thread frees it.
        assert inflight_alert_ids(QUERY_INFLIGHT_KEY) == {"run:1:1"}
        cancel.assert_any_call(self.team.id, "alerts-platform-insight:run:1:1")

    @override_settings(ALERTS_PLATFORM_INSIGHT_MAX_INFLIGHT_CHECKS=1)
    def test_the_pool_defers_what_it_cannot_hold_until_a_check_frees_its_slot(self) -> None:
        first = self._copy(self._alert(), id=UUID(int=1))
        second = self._copy(self._alert(calculation_interval=AlertCalculationInterval.REAL_TIME.value), id=UUID(int=2))
        slot = slot_of(first.next_check_at, CUTOFF)
        expires_at = time.time() + 3600

        (admitted,) = plan_insight_batch(self.team.id, slot, CUTOFF, expires_at=expires_at)
        assert admitted == str(first.id)
        assert plan_insight_batch(self.team.id, slot, CUTOFF, expires_at=expires_at + 60) == ()

        with patch(f"{_MODULE}.check_alert_for_insight", return_value=AlertEvaluationResult(value=1.0, breaches=[])):
            evaluate_insight_check(self.team.id, slot, CUTOFF, admitted, held_until=expires_at, evaluation_id="test")

        # Through the activity the workflow calls, so a dropped `exclude` or cadence there fails here too.
        replanned = plan_platform_insight_checks_activity(
            InsightBatchPlanInputs(
                evaluation=SourceEvaluationInputs(
                    source=SourceKind.INSIGHT,
                    cutoff=CUTOFF.isoformat(),
                    batch_key=AlertBatchKey(team_id=self.team.id, slot=slot),
                ),
                expires_at=expires_at,
                exclude=(admitted,),
            )
        )
        assert replanned == [AdmittedInsightCheck(configuration_id=str(second.id), real_time=True)]

    def _investigated_alert(self, **overrides: Any) -> tuple[AlertConfiguration, PlatformConfigurationSnapshot]:
        alert = self._alert(
            detector_config={"type": "zscore", "threshold": 0.95, "window": 30},
            investigation_agent_enabled=True,
            **overrides,
        )
        return alert, self._copy(alert, owner=PlatformAlertOwner.PLATFORM)

    def _fire(self, configuration: PlatformConfigurationSnapshot) -> PlatformAlertOutcome:
        with patch(f"{_MODULE}.render_alert_insight_chart_or_raise"):
            outcome, _ = self._evaluate(
                configuration,
                result=AlertEvaluationResult(
                    value=150.0, breaches=["above 100"], triggered_dates=["2026-09-16"], triggered_points=[29]
                ),
            )
        assert outcome is not None
        return outcome

    @parameterized.expand(
        [
            ("a gated alert holds its firing", True, PlatformAlertOwner.PLATFORM, True, True),
            ("an ungated alert sends its firing", False, PlatformAlertOwner.PLATFORM, True, False),
            ("a parallel run never investigates", True, PlatformAlertOwner.SOURCE, False, False),
        ]
    )
    def test_an_owned_firing_asks_for_an_investigation(
        self, _name: str, gates: bool, owner: str, investigates: bool, held: bool
    ) -> None:
        alert = self._alert(
            detector_config={"type": "zscore", "threshold": 0.95, "window": 30},
            investigation_agent_enabled=True,
            investigation_gates_notifications=gates,
        )
        configuration = self._copy(alert, owner=owner)

        outcome = self._fire(configuration)

        assert (requested_investigation(outcome) is not None) is investigates
        assert (outcome.held_delivery is not None) is held
        if owner == PlatformAlertOwner.PLATFORM:
            assert len(self.deliveries) == (0 if held else 1)

    @parameterized.expand(
        [
            ("a statistical detector renotifies", {"type": "zscore", "threshold": 0.95, "window": 30}, True),
            ("the ai detector announces the firing once", {"type": "llm"}, False),
        ]
    )
    def test_a_firing_that_stays_breached_renotifies_only_for_a_statistical_detector(
        self, _name: str, detector_config: dict[str, Any], renotifies: bool
    ) -> None:
        alert = self._alert(
            detector_config=detector_config,
            investigation_agent_enabled=True,
            investigation_gates_notifications=True,
        )
        configuration = self._copy(alert, owner=PlatformAlertOwner.PLATFORM)
        uses_llm_detector = detector_config["type"] == "llm"
        result = AlertEvaluationResult(value=150.0, breaches=["above 100"])

        with patch(f"{_MODULE}.render_alert_insight_chart_or_raise"):
            first, _ = self._evaluate(configuration, result=result, uses_llm_detector=uses_llm_detector)
            assert first is not None
            assert first.groups[0].kind == AlertEventKind.FIRING
            assert requested_investigation(first) is not None
            assert first.held_delivery is not None
            record_outcomes(self.team.id, (first,), CUTOFF)
            with team_scope(self.team.id):
                platform_testing.set_due_at(configuration.id, CUTOFF - timedelta(minutes=1))

            second, _ = self._evaluate(configuration, result=result, uses_llm_detector=uses_llm_detector)

        assert second is not None
        assert second.groups[0].new_state == "firing"
        assert (second.groups[0].kind == AlertEventKind.FIRING) is renotifies
        assert (requested_investigation(second) is not None) is renotifies
        if not renotifies:
            assert second.held_delivery is None
            assert self.deliveries == ()

    def test_a_firing_past_its_budget_is_muted_by_the_firing_last_verdict(self) -> None:
        alert, configuration = self._investigated_alert(investigation_gates_notifications=True)
        for index, verdict in enumerate(["true_positive", "true_positive", "false_positive"]):
            InsightAlertInvestigation.objects.for_team(self.team.id).create(
                team=self.team,
                alert_configuration=alert,
                configuration_id=configuration.id,
                evaluation_key=f"slot:earlier-{index}",
                episode_started_at=CUTOFF,
                kind=InsightAlertInvestigation.Kind.AGENT,
                status=InvestigationStatus.DONE,
                verdict=verdict,
            )

        outcome = self._fire(configuration)

        assert requested_investigation(outcome) is None
        assert (outcome.groups[0].kind, outcome.groups[0].muted_notification) == (AlertEventKind.CHECK, "fire")
        assert outcome.groups[0].source_detail.get(SUPPRESSED_BY_AGENT_KEY) is True
        assert self.deliveries == ()

    @parameterized.expand(
        [
            ("claimed", None, None, True),
            ("refused with no verdict yet", InvestigationStatus.RUNNING, None, False),
            ("refused after a false positive", InvestigationStatus.DONE, "false_positive", False),
        ]
    )
    def test_a_recorded_firing_claims_its_investigation_or_releases_its_hold(
        self, _name: str, earlier: str | None, verdict: str | None, claimed: bool
    ) -> None:
        alert, configuration = self._investigated_alert(investigation_gates_notifications=True)
        if earlier is not None:
            InsightAlertInvestigation.objects.for_team(self.team.id).create(
                team=self.team,
                alert_configuration=alert,
                configuration_id=configuration.id,
                evaluation_key="slot:earlier",
                episode_started_at=CUTOFF,
                kind=InsightAlertInvestigation.Kind.AGENT,
                status=earlier,
                verdict=verdict,
            )
        outcome = self._fire(configuration)
        record_outcomes(self.team.id, (outcome,), CUTOFF)

        claims = claim_requested_investigations(self.team.id, (outcome,))

        assert claims == claim_requested_investigations(self.team.id, (outcome,))
        assert len(claims.starts) == (1 if claimed else 0)
        if claimed:
            investigation = InsightAlertInvestigation.objects.for_team(self.team.id).get(
                id=claims.starts[0].investigation_id
            )
            assert investigation.evaluated["value"] == 150.0
            assert investigation.evaluated["triggered_dates"] == ["2026-09-16"]
        assert len(claims.deliveries) == (1 if not claimed and verdict is None else 0)

    def test_an_alert_insight_keeps_no_row_for_is_investigated_under_its_own_id(self) -> None:
        alert = self._alert(detector_config={"type": "zscore", "threshold": 0.95, "window": 30})
        insight = alert.insight
        configuration = self._copy(
            None,
            owner=PlatformAlertOwner.PLATFORM,
            created_by_id=self.user.id,
            source_config={
                "insight_id": insight.id,
                SOURCE_CONDITION_KEY: {"detector": alert.detector_config},
                "investigation_agent_enabled": True,
                "investigation_gates_notifications": True,
            },
        )
        alert.delete()

        outcome = self._fire(configuration)
        record_outcomes(self.team.id, (outcome,), CUTOFF)
        claims = claim_requested_investigations(self.team.id, (outcome,))

        assert outcome.held_delivery is not None
        (start,) = claims.starts
        assert (start.alert_id, start.user_id) == (str(configuration.id), self.user.id)
        investigation = InsightAlertInvestigation.objects.for_team(self.team.id).get(id=start.investigation_id)
        assert (investigation.alert_configuration_id, investigation.configuration_id) == (None, configuration.id)
        investigated = load_investigated_alert(self.team.id, configuration.id)
        assert investigated is not None
        assert (investigated.id, investigated.insight_id, investigated.investigation_gates_notifications) == (
            configuration.id,
            insight.id,
            True,
        )

    def test_a_firing_whose_investigation_cannot_be_decided_still_goes_out(self) -> None:
        _alert, configuration = self._investigated_alert(investigation_gates_notifications=True)

        with patch(f"{_MODULE}.with_investigation", side_effect=RuntimeError("database went away")):
            outcome = self._fire(configuration)

        assert outcome.held_delivery is None
        assert len(self.deliveries) == 1

    @parameterized.expand(
        [
            ("an owned firing that starts an episode", {}, PlatformAlertOwner.PLATFORM, None, 1),
            ("a parallel run leaves the signal to the insight stack", {}, PlatformAlertOwner.SOURCE, None, 0),
            (
                "an investigated alert waits for the agent's verdict",
                _AGENT_ON,
                PlatformAlertOwner.PLATFORM,
                None,
                0,
            ),
            (
                "an investigated alert with no insight stack row waits for the agent's verdict",
                _AGENT_ON,
                PlatformAlertOwner.PLATFORM,
                None,
                0,
                "all_firing_alerts",
                "native",
            ),
            (
                "a breakdown check with several firing values, which the agent never takes, signals each one",
                _AGENT_ON,
                PlatformAlertOwner.PLATFORM,
                None,
                2,
                "all_firing_alerts",
                "breakdown",
            ),
            ("an alert already firing stays in its episode", {}, PlatformAlertOwner.PLATFORM, "firing", 0),
            (
                "errors that interrupted a firing resume it",
                {},
                PlatformAlertOwner.PLATFORM,
                "errored after firing",
                0,
            ),
            (
                "errors after a quiet alert end in a new episode",
                {},
                PlatformAlertOwner.PLATFORM,
                "errored after not_firing",
                1,
            ),
            (
                "errors that began before the history window resume a firing",
                {},
                PlatformAlertOwner.PLATFORM,
                "errored before the window",
                0,
            ),
            ("a team without the all-firing scope", {}, PlatformAlertOwner.PLATFORM, None, 0, "investigated_only"),
            (
                "errors that interrupted breakdown values' firings resume them",
                {},
                PlatformAlertOwner.PLATFORM,
                "errored after firing",
                0,
                "all_firing_alerts",
                "breakdown",
            ),
            (
                "errors after quiet breakdown values end in new episodes",
                {},
                PlatformAlertOwner.PLATFORM,
                "errored after not_firing",
                2,
                "all_firing_alerts",
                "breakdown",
            ),
        ]
    )
    def test_a_firing_files_an_inbox_signal_only_when_it_starts_an_uninvestigated_episode(
        self,
        _name: str,
        overrides: dict[str, Any],
        owner: str,
        before: str | None,
        signals: int,
        scope: str = "all_firing_alerts",
        shape: str = "row",
    ) -> None:
        alert = self._alert(**overrides)
        if shape == "native":
            configuration = self._copy(
                None,
                owner=owner,
                source_config={
                    "insight_id": alert.insight_id,
                    SOURCE_CONDITION_KEY: {"detector": alert.detector_config},
                    "investigation_agent_enabled": alert.investigation_agent_enabled,
                },
            )
        elif shape == "breakdown":
            grouping = Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("breakdown",))
            configuration = self._copy(alert, owner=owner, grouping=grouping.to_stored())
        else:
            configuration = self._copy(alert, owner=owner)
        with team_scope(self.team.id):
            if before == "firing":
                platform_testing.start_firing(configuration.id, team_id=self.team.id, at=CUTOFF - timedelta(hours=1))
            elif before is not None:
                if shape == "breakdown" and before == "errored after firing":
                    for value in ("Chrome", "Firefox"):
                        platform_testing.start_firing(
                            configuration.id, team_id=self.team.id, at=CUTOFF - timedelta(hours=1), grouping_key=value
                        )
                platform_testing.set_check_status(configuration.id, "errored")
        events: tuple[PlatformCheckEvent, ...] = (_check_event(previous_state="errored", state="errored"),)
        if before != "errored before the window":
            # A breakdown alert has no ungrouped instance, so its failure row found it quiet.
            interrupted = (
                "not_firing" if shape == "breakdown" else (before or "").removeprefix("errored after ") or "not_firing"
            )
            events = (*events, _check_event(previous_state=interrupted, state="errored"))
        history = PlatformCheckEventPage(events=events, total=len(events))

        with (
            patch(f"{_EMITTER_MODULE}.get_analytics_alert_scope", return_value=scope),
            patch(
                f"{_EMITTER_MODULE}.get_source_config",
                return_value=SignalSourceConfigSnapshot(enabled=True, created_by_id=None, config={}),
            ),
            patch(f"{_EMITTER_MODULE}.get_analytics_alert_name_patterns", return_value=AlertNamePatterns()),
            patch(f"{_FIRING_SIGNAL_MODULE}.platform.notable_checks_by_public_id", return_value=history),
        ):
            if shape == "breakdown":
                outcome = self._evaluate_per_series(configuration, {"Chrome": 150.0, "Safari": 40.0, "Firefox": 120.0})
            else:
                outcome = self._fire(configuration)
            record_outcomes(self.team.id, (outcome,), CUTOFF)
            with patch(
                f"{_FIRING_SIGNAL_MODULE}.platform.get_configuration", wraps=platform_facade.get_configuration
            ) as reads:
                prepared = prepare_platform_firing_signals(requested_firing_signals(self.team.id, (outcome,)))

        assert len(prepared) == signals
        assert len({signal.alert_check_id for signal in prepared}) == signals
        assert reads.call_count <= 1

    @parameterized.expand(
        [
            ("an owned alert files its signal", None, 1),
            ("an alert disabled since files none", "disabled", 0),
            ("a firing the record skipped files none", "unrecorded", 0),
        ]
    )
    def test_a_recorded_firing_files_its_signal_while_the_platform_owns_the_alert(
        self, _name: str, change: str | None, signals: int
    ) -> None:
        # A detector without the agent, because only a detector check keeps the dates it fired on.
        alert = self._alert(
            owner=PlatformAlertOwner.PLATFORM, detector_config={"type": "zscore", "threshold": 0.95, "window": 30}
        )
        configuration = self._copy(alert, owner=PlatformAlertOwner.PLATFORM)
        with patch(f"{_EMITTER_MODULE}.get_analytics_alert_scope", return_value="all_firing_alerts"):
            outcome = self._fire(configuration)
        if change != "unrecorded":
            record_outcomes(self.team.id, (outcome,), CUTOFF)
        if change == "disabled":
            with team_scope(self.team.id):
                platform_testing.set_enabled(configuration.id, False)

        with (
            patch(
                f"{_EMITTER_MODULE}.get_source_config",
                return_value=SignalSourceConfigSnapshot(enabled=True, created_by_id=None, config={}),
            ),
            patch(f"{_EMITTER_MODULE}.get_analytics_alert_scope", return_value="all_firing_alerts"),
            patch(f"{_EMITTER_MODULE}.get_analytics_alert_name_patterns", return_value=AlertNamePatterns()),
        ):
            prepared = prepare_platform_firing_signals(requested_firing_signals(self.team.id, (outcome,)))

        assert len(prepared) == signals
        if prepared:
            (request,) = requested_firing_signals(self.team.id, (outcome,))
            assert prepared[0].alert_check_id == f"{configuration.id}:{request.episode_started_at.isoformat()}"
            assert prepared[0].extra["breaches"] == ["above 100"]
            assert prepared[0].extra["triggered_dates"] == ["2026-09-16"]

    @parameterized.expand(
        [
            ("owned by the platform", PlatformAlertOwner.PLATFORM, True),
            ("owned by its source", PlatformAlertOwner.SOURCE, False),
        ]
    )
    def test_a_firing_of_an_alert_with_no_insight_stack_row_files_its_signal(
        self, _name: str, owner: str, files: bool
    ) -> None:
        insight = self._alert().insight
        configuration = self._copy(
            None,
            owner=owner,
            source_config={"insight_id": insight.id, SOURCE_CONDITION_KEY: {"detector": {"type": "zscore"}}},
        )
        request = FiringSignalRequest(
            team_id=self.team.id,
            alert_id=str(configuration.id),
            configuration_id=str(configuration.id),
            episode_started_at=CUTOFF,
            breaches=("above 100",),
        )
        with team_scope(self.team.id):
            platform_testing.start_firing(configuration.id, team_id=self.team.id, at=CUTOFF)

        with (
            patch(
                f"{_EMITTER_MODULE}.get_source_config",
                return_value=SignalSourceConfigSnapshot(enabled=True, created_by_id=None, config={}),
            ),
            patch(f"{_EMITTER_MODULE}.get_analytics_alert_scope", return_value="all_firing_alerts"),
            patch(f"{_EMITTER_MODULE}.get_analytics_alert_name_patterns", return_value=AlertNamePatterns()),
        ):
            prepared = prepare_platform_firing_signals((request,))

        assert len(prepared) == (1 if files else 0)
        if not files:
            return
        (signal,) = prepared
        assert (signal.alert_id, signal.extra["insight_id"], signal.extra["detector_type"]) == (
            str(configuration.id),
            str(insight.id),
            "zscore",
        )
        assert signal.extra["url"].endswith(f"?alert_id={configuration.id}")

    @parameterized.expand([("found", None, InvestigationStatus.DONE), ("failed", RuntimeError("no data"), "failed")])
    def test_a_metrics_firing_is_held_until_its_investigation_ends(
        self, _name: str, error: Exception | None, status: str
    ) -> None:
        alert = self._alert(investigation_agent_enabled=True, investigation_gates_notifications=True)
        alert.insight.query = {"kind": "MetricsQuery", "clauses": [{"name": "a", "metricName": "queue.depth"}]}
        alert.insight.save()
        configuration = self._copy(alert, owner=PlatformAlertOwner.PLATFORM)
        outcome = self._fire(configuration)
        record_outcomes(self.team.id, (outcome,), CUTOFF)

        claims = claim_requested_investigations(self.team.id, (outcome,))
        with patch(
            "products.alerts.backend.platform_investigation.investigate_metrics_alert",
            side_effect=error,
            return_value="queue.depth moved up.",
        ) as investigate:
            released = [
                run_platform_metrics_investigations_activity(MetricsInvestigationsInputs(runs=claims.metrics))
                for _ in range(2)
            ]

        assert outcome.held_delivery is not None
        assert self.deliveries == ()
        assert (claims.starts, len(claims.metrics)) == ((), 1)
        # Released once the run ends, whatever it found, and a retry gets the same request back.
        assert released == [[outcome.held_delivery.request]] * 2
        investigate.assert_called_once()
        assert investigate.call_args.kwargs["fired_at"] == CUTOFF
        investigation = InsightAlertInvestigation.objects.for_team(self.team.id).get()
        assert (investigation.kind, investigation.status) == (InsightAlertInvestigation.Kind.METRICS, status)
        assert investigation.summary == ("queue.depth moved up." if error is None else None)

    def test_a_skipped_check_of_a_firing_alert_asks_for_no_investigation(self) -> None:
        _alert, configuration = self._investigated_alert(investigation_gates_notifications=True)
        record_outcomes(self.team.id, (self._fire(configuration),), CUTOFF)
        with team_scope(self.team.id):
            platform_testing.set_due_at(configuration.id, CUTOFF - timedelta(minutes=1))

        outcome, _ = self._evaluate(
            configuration, result=AlertEvaluationResult(value=None, breaches=[], skipped_reason="not enough data")
        )

        assert outcome is not None
        assert outcome.skipped
        assert requested_investigation(outcome) is None

    def test_a_metrics_run_past_its_activity_deadline_is_recorded_as_failed(self) -> None:
        alert = self._alert(investigation_agent_enabled=True)
        alert.insight.query = {"kind": "MetricsQuery", "clauses": [{"name": "a", "metricName": "queue.depth"}]}
        alert.insight.save()
        configuration = self._copy(alert, owner=PlatformAlertOwner.PLATFORM)
        outcome = self._fire(configuration)
        record_outcomes(self.team.id, (outcome,), CUTOFF)
        claims = claim_requested_investigations(self.team.id, (outcome,))

        with (
            patch("products.alerts.backend.temporal.platform_evaluate.time.monotonic", side_effect=[0.0, 10_000.0]),
            patch("products.alerts.backend.platform_investigation.investigate_metrics_alert") as investigate,
        ):
            run_platform_metrics_investigations_activity(MetricsInvestigationsInputs(runs=claims.metrics))

        investigate.assert_not_called()
        investigation = InsightAlertInvestigation.objects.for_team(self.team.id).get()
        assert investigation.status == InvestigationStatus.FAILED
