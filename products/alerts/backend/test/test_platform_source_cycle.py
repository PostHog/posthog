import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import get_query_tags
from posthog.constants import AvailableFeature
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseClusterMemoryLimitExceeded
from posthog.models.scoping import team_scope
from posthog.redis import get_client
from posthog.schema_enums import AlertCalculationInterval
from posthog.tasks.alerts.utils import AlertEvaluationResult, RenderedInsightChart, next_check_time
from posthog.temporal.alerts.admission import inflight_alert_ids, release_evaluation_slot

from products.alerts.backend.evaluation.contract import AlertExtractionError
from products.alerts.backend.evaluation.dispatcher import PerSeriesEvaluation, SeriesEvaluation
from products.alerts.backend.judge.contract import (
    LLM_DETECTOR_UNAVAILABLE_MESSAGE,
    LLMDetectorMisconfiguredError,
    LLMDetectorUnavailableError,
)
from products.alerts.backend.logic.alert_email import INSIGHT_ALERT_ERRORED_EVENT_ID
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.alerts.backend.platform_alert_wording import insight_alert_url
from products.alerts.backend.platform_source_cycle import (
    CAPACITY_REJECTED,
    INFLIGHT_KEY,
    MAX_BREACH_CHARS,
    evaluate_insight_check,
    plan_insight_batch,
    readmit_retried_check,
)
from products.alerts.backend.temporal.platform_evaluate import (
    AdmittedInsightCheck,
    InsightBatchPlanInputs,
    plan_platform_insight_checks_activity,
)
from products.alerts.backend.test.insight_alerts import create_insight_alert
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import list_configurations, record_outcomes, slot_of
from products.alerts_platform.backend.facade.contracts import (
    AlertBatchKey,
    AlertEventKind,
    Grouping,
    GroupingMode,
    PlatformAlertOutcome,
    PlatformConfigurationSnapshot,
    SourceEvaluationInputs,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner

_MODULE = "products.alerts.backend.platform_source_cycle"
# A Wednesday, so no weekend rule applies.
CUTOFF = datetime(2026, 9, 16, 10, tzinfo=UTC)


class TestPlatformInsightEvaluation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        get_client().delete(INFLIGHT_KEY)
        self.addCleanup(get_client().delete, INFLIGHT_KEY)
        self.organization.available_product_features = [
            {"key": AvailableFeature.HIGH_FREQUENCY_ALERTS, "name": "High-frequency alerts"},
            {"key": AvailableFeature.REAL_TIME_ALERTS, "name": "Real-time alerts"},
        ]
        self.organization.save()

    def _alert(self, **overrides: Any) -> AlertConfiguration:
        return create_insight_alert(self.team, **{"next_check_at": CUTOFF - timedelta(minutes=1), **overrides})

    def _copy(self, alert: AlertConfiguration | None, **overrides: Any) -> PlatformConfigurationSnapshot:
        with team_scope(self.team.id):
            return platform_testing.create_configuration(
                **{
                    "team_id": self.team.id,
                    "name": "alert",
                    "source_kind": SourceKind.INSIGHT,
                    "source_config": {},
                    "check_interval_minutes": 60 * 24,
                    "recurrence_unit": "day",
                    "next_check_at": CUTOFF - timedelta(minutes=1),
                    "legacy_configuration_id": alert.id if alert else None,
                    **overrides,
                }
            )

    def _evaluate_per_series(
        self,
        configuration: PlatformConfigurationSnapshot,
        values: dict[str, float] | list[tuple[str, float]],
        *,
        truncated: bool = False,
        breach: str = "above 100",
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
        with patch(f"{_MODULE}.check_alert_per_series", return_value=evaluated):
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
        side_effect = result if isinstance(result, Exception) else None
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

    @parameterized.expand(
        [
            ("source_owned", "source", {}),
            ("platform_owned", "platform", {"insight_chart_asset_id": 7, "insight_chart_render_user_id": 3}),
        ]
    )
    def test_a_firing_records_what_production_sends_beside_it(
        self, _name: str, owner: str, chart: dict[str, Any]
    ) -> None:
        alert = self._alert()
        configuration = self._copy(alert, owner=owner)
        expected = {
            "breaches": ["above 100"],
            "insight_name": alert.insight.name,
            "insight_short_id": alert.insight.short_id,
            "alert_id": str(alert.id),
            **chart,
        }

        with patch(
            f"{_MODULE}.render_alert_insight_chart",
            return_value=RenderedInsightChart(asset_id=7, render_user_id=3),
        ) as render:
            outcome, _ = self._evaluate(
                configuration, result=AlertEvaluationResult(value=150.0, breaches=["above 100"])
            )

        assert outcome is not None
        assert outcome.groups[0].source_detail == expected
        # A render costs up to a minute and a half, so the parallel run must never pay for one.
        assert render.called is (owner == "platform")

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

        outcome, _ = self._evaluate(configuration, result=AlertEvaluationResult(value=150.0, breaches=["above 100"]))
        assert outcome is not None
        assert get_query_tags().ch_user == ClickHouseUser.ALERTS_PLATFORM_INSIGHT
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
    ) -> None:
        # A half-hour timezone, where the local hour starts at :30 UTC.
        self.team.timezone = "Asia/Kolkata"
        self.team.save()
        restriction = {"blocked_windows": [{"start": quiet[0], "end": quiet[1]}]} if quiet else None
        alert = self._alert(
            calculation_interval=interval, schedule_restriction=restriction, schedule_start_time=start_time
        )
        configuration = self._copy(
            alert,
            check_interval_minutes=minutes,
            recurrence_unit=unit,
            schedule_restriction=restriction,
            anchor_time=start_time,
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
            ("allowlisted", True, False, False),
            ("not_allowlisted", False, False, False),
            ("allowlisted_resolve", True, True, False),
            ("platform_owned", False, False, True),
        ]
    )
    def test_only_an_allowlisted_or_platform_owned_firing_or_failure_asks_for_a_delivery(
        self, _name: str, allowlisted: bool, was_firing: bool, owned: bool
    ) -> None:
        alert = self._alert()
        configuration = self._copy(alert, **({"owner": PlatformAlertOwner.PLATFORM} if owned else {}))
        allowlist = frozenset({str(alert.id)}) if allowlisted else frozenset()
        if was_firing:
            fired, _ = self._evaluate(configuration, result=AlertEvaluationResult(value=150.0, breaches=["above 100"]))
            assert fired is not None
            record_outcomes(self.team.id, (fired,), CUTOFF)
            with team_scope(self.team.id):
                platform_testing.set_due_at(configuration.id, CUTOFF - timedelta(minutes=1))

        with patch(f"{_MODULE}.LIVE_DELIVERY_INSIGHT_ALERT_IDS", allowlist):
            self._evaluate(
                configuration,
                result=AlertEvaluationResult(value=50.0, breaches=[] if was_firing else ["above 100"]),
            )

        expected = [
            (
                str(configuration.id),
                str(alert.id),
                {"firing": "$insight_alert_firing", "errored": INSIGHT_ALERT_ERRORED_EVENT_ID},
                owned,
            )
        ]
        assert [
            (
                delivery.configuration_id,
                delivery.destination_alert_id,
                delivery.event_ids_by_kind,
                delivery.owned_by_platform,
            )
            for delivery in self.deliveries
        ] == (expected if (allowlisted or owned) and not was_firing else [])
        # A native message links to the alert on its insight, where the insight stack's messages link.
        assert all(
            delivery.source_alert_url == insight_alert_url(self.team.id, alert.insight.short_id, str(alert.id))
            for delivery in self.deliveries
        )

    @parameterized.expand(
        [
            ("disabled", {"enabled": False}, "not_firing"),
            ("snoozed", {"snoozed_until": CUTOFF + timedelta(hours=1)}, "snoozed"),
        ]
    )
    def test_a_check_production_would_not_run_is_recorded_without_a_query(
        self, _name: str, overrides: dict[str, Any], state: str
    ) -> None:
        outcome, query = self._evaluate(self._copy(self._alert(**overrides)))

        query.assert_not_called()
        assert outcome is not None
        assert (outcome.groups[0].kind, outcome.groups[0].new_state, outcome.disable) == (
            AlertEventKind.CHECK,
            state,
            False,
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

    def test_a_copy_whose_production_alert_is_gone_is_disabled(self) -> None:
        outcome, query = self._evaluate(self._copy(None))

        query.assert_not_called()
        assert outcome is not None and outcome.disable

    @parameterized.expand(
        [
            ("too_many_queries", ClickHouseAtCapacity()),
            ("cluster_memory_full", ClickHouseClusterMemoryLimitExceeded()),
        ]
    )
    def test_a_check_clickhouse_refuses_for_load_leaves_the_alert_as_it_was(self, _name: str, error: Exception) -> None:
        outcome, _ = self._evaluate(self._copy(self._alert()), result=error)

        assert outcome is not None
        assert (outcome.groups[0].kind, outcome.groups[0].new_state, outcome.error_message, outcome.disable) == (
            AlertEventKind.CHECK,
            "not_firing",
            CAPACITY_REJECTED,
            False,
        )

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
            ("ai_consent_withdrawn", LLMDetectorMisconfiguredError("consent withdrawn")),
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

    @override_settings(ALERTS_PLATFORM_INSIGHT_MAX_INFLIGHT_EVALUATIONS=1)
    def test_a_retry_stops_the_timed_out_query_and_runs_only_inside_the_pool(self) -> None:
        held = self._copy(self._alert(), id=UUID(int=1))
        waiting = self._copy(self._alert(), id=UUID(int=2))
        slot = slot_of(held.next_check_at, CUTOFF)
        expires_at = time.time() + 3600
        assert plan_insight_batch(self.team.id, slot, CUTOFF, expires_at=expires_at) == (str(held.id),)

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
        cancel.assert_any_call(self.team.id, "alerts-platform-insight:run:1:1")

    @override_settings(ALERTS_PLATFORM_INSIGHT_MAX_INFLIGHT_EVALUATIONS=1)
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
