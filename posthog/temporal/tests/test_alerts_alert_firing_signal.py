from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.schema import AlertState

from posthog.redis import TEST_clear_clients
from posthog.temporal.alerts.alert_firing_signal import dispatch_alert_firing_signal, prepare_alert_firing_signal
from posthog.token_bucket import Budget, TEST_reset_scripts

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.facade.api import validate_signal_input
from products.signals.backend.facade.source_configs import SignalSourceConfigSnapshot

_MODULE = "posthog.temporal.alerts.alert_firing_signal"


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
        ]
    )
    def test_cap_counts_only_dispatched_signals(self, _name: str, first_emit: dict, second_expected: bool) -> None:
        first = self._alert_and_check()
        second = self._alert_and_check()

        with patch(f"{_MODULE}.CAP_BUDGET", Budget(burst=1, per_hour=1)):
            self._emit(*first, emit=AsyncMock(**first_emit))
            emitted, _ = self._emit(*second)

        assert emitted is second_expected
