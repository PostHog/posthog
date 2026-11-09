from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.models.scoping import team_scope
from posthog.redis import TEST_clear_clients
from posthog.temporal.alerts.alert_firing_signal import dispatch_alert_firing_signal
from posthog.token_bucket import TEST_reset_scripts

from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_firing_signal import prepare_platform_firing_signal
from products.alerts.backend.platform_firing_signal_detail import FiringSignalRequest
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.contracts import SOURCE_CONDITION_KEY, SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.facade.api import validate_signal_input
from products.signals.backend.facade.source_configs import AlertNamePatterns, SignalSourceConfigSnapshot

_SIGNAL_MODULE = "posthog.temporal.alerts.alert_firing_signal"


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


class TestPlatformFiringSignal(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        TEST_clear_clients()
        TEST_reset_scripts()
        self.addCleanup(TEST_clear_clients)
        self.addCleanup(TEST_reset_scripts)
        self.insight = Insight.objects.create(team=self.team, name="Daily signups", query={})

    @parameterized.expand(
        [
            ("alert_with_no_insight_stack_row", {}, False, True),
            ("copy_of_an_alert_the_agent_investigates", {}, True, False),
            ("switched_off_since_the_check", {"enabled": False}, False, False),
        ]
    )
    def test_an_owned_firing_signals_from_the_platform_alert_and_its_insight(
        self, _name: str, overrides: dict, investigated_copy: bool, expected: bool
    ) -> None:
        legacy = (
            AlertConfiguration.objects.create(
                team=self.team,
                insight=self.insight,
                name="Signups dropped",
                investigation_agent_enabled=True,
                detector_config={"type": "zscore"},
                created_by=self.user,
            )
            if investigated_copy
            else None
        )
        with team_scope(self.team.id):
            configuration = platform_testing.create_configuration(
                **{
                    "team_id": self.team.id,
                    "name": "Checkout errors",
                    "source_kind": SourceKind.INSIGHT,
                    "source_config": {"insight_id": self.insight.id, SOURCE_CONDITION_KEY: {"detector": None}},
                    "check_interval_minutes": 60,
                    "owner": PlatformAlertOwner.PLATFORM,
                    "legacy_configuration_id": legacy.id if legacy else None,
                    **overrides,
                }
            )
        request = FiringSignalRequest(
            team_id=self.team.id,
            configuration_id=str(configuration.id),
            evaluation_key="slot:2026-09-16T10:00:00+00:00",
            episode_started_at="2026-09-16T10:00:00+00:00",
            breaches=("The value is above the threshold",),
        )
        emit = AsyncMock(side_effect=_validated_emit)

        with (
            patch(f"{_SIGNAL_MODULE}.emit_signal", emit),
            patch(
                f"{_SIGNAL_MODULE}.get_source_config",
                return_value=SignalSourceConfigSnapshot(enabled=True, created_by_id=None, config={}),
            ),
            patch(f"{_SIGNAL_MODULE}.get_analytics_alert_scope", return_value="all_firing_alerts"),
            patch(f"{_SIGNAL_MODULE}.get_analytics_alert_name_patterns", return_value=AlertNamePatterns()),
        ):
            signal = prepare_platform_firing_signal(request)
            emitted = signal is not None and async_to_sync(dispatch_alert_firing_signal)(signal)

        assert emitted is expected
        if expected:
            assert emit.await_args is not None
            kwargs = emit.await_args.kwargs
            source_id = f"{configuration.id}:{configuration.id}:{request.evaluation_key}"
            assert kwargs["source_id"] == kwargs["idempotency_key"] == source_id
            extra = kwargs["extra"]
            assert (extra["alert_name"], extra["insight_id"], extra["url"].split("/project/")[1]) == (
                "Checkout errors",
                str(self.insight.id),
                f"{self.team.id}/insights/{self.insight.short_id}?alert_id={configuration.id}",
            )
        else:
            emit.assert_not_awaited()
