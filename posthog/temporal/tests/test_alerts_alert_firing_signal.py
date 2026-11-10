import asyncio
import contextlib
from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.schema import AlertState

from posthog.redis import TEST_clear_clients
from posthog.temporal.alerts.alert_firing_signal import (
    CAP_DROP_EVENT,
    EMITTED_OUTCOME,
    AlertFiringSkipReason,
    FiringAlert,
    FiringStart,
    cap_key,
    dispatch_alert_firing_signal,
    prepare_alert_firing_signal,
    prepare_platform_firing_signal,
)
from posthog.token_bucket import BucketUnavailable, Budget, TEST_reset_scripts, consume

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.facade.api import validate_signal_input
from products.signals.backend.facade.source_configs import AlertNamePatterns, SignalSourceConfigSnapshot

_MODULE = "posthog.temporal.alerts.alert_firing_signal"
_ONE_TOKEN = Budget(burst=1, per_hour=1)
_OUTCOMES = [EMITTED_OUTCOME, *(reason.value for reason in AlertFiringSkipReason)]


def _outcome_counts() -> dict[str, float]:
    return {
        outcome: REGISTRY.get_sample_value("posthog_insight_alerts_firing_signals_total", {"outcome": outcome}) or 0.0
        for outcome in _OUTCOMES
    }


def _counted_since(before: dict[str, float]) -> dict[str, float]:
    return {
        outcome: count - before[outcome] for outcome, count in _outcome_counts().items() if count != before[outcome]
    }


def _source(enabled: bool) -> SignalSourceConfigSnapshot:
    return SignalSourceConfigSnapshot(enabled=enabled, created_by_id=None, config={})


async def _validated_emit(**kwargs) -> bool:
    validate_signal_input(
        source_product=kwargs["source_product"],
        source_type=kwargs["source_type"],
        source_id=kwargs["source_id"],
        description=kwargs["description"],
        weight=kwargs["weight"],
        extra=kwargs["extra"],
        remediation=None,
    )
    return True


async def _hang(**_kwargs) -> bool:
    await asyncio.Event().wait()
    return True


class TestEmitAlertFiringSignal(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        TEST_clear_clients()
        TEST_reset_scripts()
        self.addCleanup(TEST_clear_clients)
        self.addCleanup(TEST_reset_scripts)
        self.insight = Insight.objects.create(team=self.team, name="Daily signups", query={})

    def _alert_and_check(
        self,
        *,
        investigation_agent_enabled: bool = False,
        detector_config: dict | None = None,
        earlier_states: list[AlertState] | None = None,
    ) -> tuple[AlertConfiguration, AlertCheck]:
        alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=self.insight,
            name="Signups dropped",
            state=AlertState.FIRING,
            investigation_agent_enabled=investigation_agent_enabled,
            detector_config=detector_config,
            created_by=self.user,
        )
        for state in earlier_states or []:
            AlertCheck.objects.create(alert_configuration=alert, state=state, calculated_value=1.0)
        check = AlertCheck.objects.create(alert_configuration=alert, state=AlertState.FIRING, calculated_value=1.0)
        return alert, check

    def _emit(
        self,
        alert: AlertConfiguration,
        check: AlertCheck,
        *,
        previous_state: str = AlertState.NOT_FIRING,
        scope: str = "all_firing_alerts",
        source_enabled: bool | None = True,
        patterns: AlertNamePatterns | None = None,
        emit: AsyncMock | None = None,
    ) -> tuple[bool, AsyncMock]:
        emit = emit or AsyncMock(side_effect=_validated_emit)
        with (
            patch(f"{_MODULE}.emit_signal", emit),
            patch(
                f"{_MODULE}.get_source_config",
                return_value=None if source_enabled is None else _source(source_enabled),
            ),
            patch(f"{_MODULE}.get_analytics_alert_scope", return_value=scope),
            patch(f"{_MODULE}.get_analytics_alert_name_patterns", return_value=patterns or AlertNamePatterns()),
        ):
            signal = prepare_alert_firing_signal(
                alert, check, previous_state=previous_state, breaches=["The value is above the threshold"]
            )
            emitted = signal is not None and async_to_sync(dispatch_alert_firing_signal)(signal)
        return emitted, emit

    @parameterized.expand(
        [
            ("new_episode_without_agent", {}, {}, True),
            ("threshold_alert_with_agent_flag_is_never_investigated", {"investigation_agent_enabled": True}, {}, True),
            (
                "investigated_alert_keeps_the_verdict_gate",
                {"investigation_agent_enabled": True, "detector_config": {"type": "zscore"}},
                {},
                False,
            ),
            ("still_firing_is_the_same_episode", {}, {"previous_state": AlertState.FIRING}, False),
            (
                "error_during_an_episode_is_the_same_episode",
                {"earlier_states": [AlertState.FIRING, AlertState.ERRORED, AlertState.ERRORED]},
                {"previous_state": AlertState.ERRORED},
                False,
            ),
            (
                "error_before_the_first_fire_starts_an_episode",
                {"earlier_states": [AlertState.NOT_FIRING, AlertState.ERRORED]},
                {"previous_state": AlertState.ERRORED},
                True,
            ),
            ("default_scope", {}, {"scope": "investigated_only"}, False),
            ("source_disabled", {}, {"source_enabled": False}, False),
            ("no_source_row", {}, {"source_enabled": None}, False),
            (
                "allow_pattern_matching_the_insight_name",
                {},
                {"patterns": AlertNamePatterns(allow=("^Daily",))},
                True,
            ),
        ]
    )
    def test_emits_once_per_episode_only_when_every_gate_passes(
        self, _name: str, alert_kwargs: dict, emit_kwargs: dict, expected: bool
    ) -> None:
        alert, check = self._alert_and_check(**alert_kwargs)

        emitted, emit = self._emit(alert, check, **emit_kwargs)

        assert emitted is expected
        if expected:
            emit.assert_awaited_once()
            assert emit.await_args is not None
            kwargs = emit.await_args.kwargs
            assert (kwargs["source_product"], kwargs["source_type"]) == ("analytics", "alert_firing")
            assert kwargs["source_id"] == kwargs["idempotency_key"] == f"{alert.id}:{check.id}"
        else:
            emit.assert_not_awaited()

    @parameterized.expand(
        [
            ("dispatched_spends_the_cap", {"return_value": True}, False),
            ("not_dispatched_refunds_it", {"return_value": False}, True),
            ("emission_error_is_swallowed_and_refunds_it", {"side_effect": RuntimeError("temporal down")}, True),
            ("hung_emission_times_out_and_refunds_it", {"side_effect": _hang}, True),
            ("cancelled_attempt_refunds_it", {"side_effect": asyncio.CancelledError()}, True),
        ]
    )
    def test_cap_counts_only_dispatched_signals(self, _name: str, first_emit: dict, second_expected: bool) -> None:
        first = self._alert_and_check()
        second = self._alert_and_check()

        with (
            patch(f"{_MODULE}.CAP_BUDGET", Budget(burst=1, per_hour=1)),
            patch(f"{_MODULE}.EMISSION_TIMEOUT_SECONDS", 0.05),
        ):
            with contextlib.suppress(asyncio.CancelledError):
                self._emit(*first, emit=AsyncMock(**first_emit))
            emitted, _ = self._emit(*second)

        assert emitted is second_expected

    @parameterized.expand(
        [
            ("blocked_by_the_alert_name", AlertNamePatterns(block=("dropped$",))),
            ("not_allowed", AlertNamePatterns(allow=("(?i)checkout",))),
            ("invalid_stored_patterns", AlertNamePatterns(invalid=True)),
        ]
    )
    def test_filtered_alert_emits_nothing_and_spends_no_cap(self, _name: str, patterns: AlertNamePatterns) -> None:
        filtered = self._alert_and_check()
        passing = self._alert_and_check()

        with patch(f"{_MODULE}.CAP_BUDGET", Budget(burst=1, per_hour=1)):
            filtered_emitted, filtered_emit = self._emit(*filtered, patterns=patterns)
            passing_emitted, _ = self._emit(*passing)

        assert filtered_emitted is False
        filtered_emit.assert_not_awaited()
        assert passing_emitted is True

    def _spend_the_only_token(self) -> None:
        consume(cap_key(self.team.id), _ONE_TOKEN)

    @parameterized.expand(
        [
            ("emitted", {}, {}, None, EMITTED_OUTCOME),
            ("not_new_episode_is_not_counted", {"previous_state": AlertState.FIRING}, {}, None, None),
            (
                "investigated_is_not_counted",
                {},
                {"investigation_agent_enabled": True, "detector_config": {"type": "zscore"}},
                None,
                None,
            ),
            ("source_disabled", {"source_enabled": False}, {}, None, "source_disabled"),
            ("scope", {"scope": "investigated_only"}, {}, None, "scope"),
            ("filtered", {"patterns": AlertNamePatterns(block=("dropped$",))}, {}, None, "filtered"),
            ("filter_invalid", {"patterns": AlertNamePatterns(invalid=True)}, {}, None, "filter_invalid"),
            ("cap", {}, {}, "spend", "cap"),
            ("cap_unavailable", {}, {}, "unavailable", "cap_unavailable"),
            ("not_dispatched", {"emit": AsyncMock(return_value=False)}, {}, None, "not_dispatched"),
        ]
    )
    def test_records_each_counted_outcome_once(
        self, _name: str, emit_kwargs: dict, alert_kwargs: dict, cap_state: str | None, expected: str | None
    ) -> None:
        alert, check = self._alert_and_check(**alert_kwargs)
        before = _outcome_counts()

        with (
            patch(f"{_MODULE}.CAP_BUDGET", _ONE_TOKEN),
            patch(f"{_MODULE}.posthoganalytics.capture") as capture,
            patch(f"{_MODULE}.consume", return_value=BucketUnavailable(error="down"))
            if cap_state == "unavailable"
            else contextlib.nullcontext(),
        ):
            if cap_state == "spend":
                self._spend_the_only_token()
            self._emit(alert, check, **emit_kwargs)

        assert _counted_since(before) == ({expected: 1.0} if expected else {})
        if expected in ("cap", "cap_unavailable"):
            capture.assert_called_once()
            assert capture.call_args.kwargs["event"] == CAP_DROP_EVENT
            assert capture.call_args.kwargs["properties"] == {
                "source_product": "analytics",
                "source_type": "alert_firing",
                "source_id": f"{alert.id}:{check.id}",
                "team_id": self.team.id,
                "alert_id": str(alert.id),
                "alert_check_id": str(check.id),
                "reason": expected,
            }
        else:
            capture.assert_not_called()

    def test_retried_attempt_does_not_count_the_episode_twice(self) -> None:
        alert, check = self._alert_and_check()
        before = _outcome_counts()

        with (
            patch(f"{_MODULE}.CAP_BUDGET", _ONE_TOKEN),
            patch(f"{_MODULE}.posthoganalytics.capture") as capture,
        ):
            first, _ = self._emit(alert, check)
            retried, _ = self._emit(alert, check)

        assert (first, retried) == (True, False)
        assert _counted_since(before) == {EMITTED_OUTCOME: 1.0}
        capture.assert_not_called()

    def test_a_retried_platform_batch_spends_no_token_on_a_firing_it_already_sent(self) -> None:
        alert = FiringAlert.of(self._alert_and_check()[0])
        sent, unsent = (
            FiringStart(check_id=f"{alert.id}:{episode}", started_at=datetime(2026, 9, 16, tzinfo=UTC))
            for episode in ("a", "b")
        )

        def emit_batch(firings: tuple[FiringStart, ...]) -> list[bool]:
            with (
                patch(f"{_MODULE}.emit_signal", AsyncMock(side_effect=_validated_emit)),
                patch(f"{_MODULE}.get_source_config", return_value=_source(True)),
                patch(f"{_MODULE}.get_analytics_alert_scope", return_value="all_firing_alerts"),
                patch(f"{_MODULE}.get_analytics_alert_name_patterns", return_value=AlertNamePatterns()),
            ):
                signals = [
                    prepare_platform_firing_signal(alert, firing, breaches=[], investigated=False) for firing in firings
                ]
                return [
                    signal is not None and async_to_sync(dispatch_alert_firing_signal)(signal) for signal in signals
                ]

        with patch(f"{_MODULE}.CAP_BUDGET", Budget(burst=2, per_hour=1)):
            first_attempt = emit_batch((sent,))
            retry = emit_batch((sent, unsent))

        assert (first_attempt, retry) == ([True], [False, True])

    @parameterized.expand(
        [
            ("failed_capture_on_a_cap_drop", "spend", "posthoganalytics.capture", False),
            ("failed_counter_on_an_emitted_signal", None, "record_alert_firing_signal_outcome", True),
        ]
    )
    def test_telemetry_failure_does_not_change_the_result(
        self, _name: str, cap_state: str | None, failing: str, expected: bool
    ) -> None:
        alert, check = self._alert_and_check()

        with (
            patch(f"{_MODULE}.CAP_BUDGET", _ONE_TOKEN),
            patch(f"{_MODULE}.{failing}", side_effect=RuntimeError("telemetry down")),
        ):
            if cap_state == "spend":
                self._spend_the_only_token()
            emitted, emit = self._emit(alert, check)

        assert emitted is expected
        assert emit.await_count == int(expected)
