from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import OperationalError, connection

from posthog.models import Team

from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner, PlatformAlertState
from products.alerts_platform.backend.logic.inventory import (
    AlertCount,
    ConfigurationCount,
    SourceInventory,
    count_inventory,
)
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration
from products.alerts_platform.backend.temporal.inventory_metrics import push_inventory

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
EARLIER = NOW - timedelta(hours=1)


class TestSourceInventory(BaseTest):
    def _configuration(
        self,
        team: Team,
        *,
        source: SourceKind = SourceKind.LOGS,
        enabled: bool = True,
        owner: PlatformAlertOwner = PlatformAlertOwner.SOURCE,
        snooze_until: datetime | None = None,
        alerts: list[tuple[str, datetime | None]] | None = None,
    ) -> None:
        configuration = PlatformAlertConfiguration.objects.unscoped().create(
            team=team,
            name="alert",
            enabled=enabled,
            owner=owner,
            source_kind=source.value,
            source_config={},
            check_interval_minutes=5,
            snooze_until=snooze_until,
        )
        for index, (state, alert_snooze) in enumerate(alerts or []):
            PlatformAlert.objects.unscoped().create(
                team=team,
                configuration=configuration,
                grouping_key=str(index),
                state=state,
                snooze_until=alert_snooze,
            )

    def test_counts_each_source_across_teams_split_by_state_and_mute(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        self._configuration(
            self.team,
            alerts=[("firing", None), ("firing", LATER), ("not_firing", EARLIER)],
        )
        self._configuration(other_team, snooze_until=LATER, alerts=[("firing", None)])
        self._configuration(other_team, owner=PlatformAlertOwner.PLATFORM, alerts=[("broken", None)])
        self._configuration(other_team, enabled=False, alerts=[("firing", None)])
        self._configuration(self.team, source=SourceKind.INSIGHT, alerts=[("firing", None)])

        by_source = {inventory.source: inventory for inventory in count_inventory(NOW)}

        assert set(by_source) == set(SourceKind)
        logs = by_source[SourceKind.LOGS]
        assert {(c.enabled, c.owner.value): c.count for c in logs.configurations} == {
            (True, "source"): 2,
            (True, "platform"): 1,
            (False, "source"): 1,
            (False, "platform"): 0,
        }
        assert {(a.state.value, a.muted): a.count for a in logs.alerts if a.count} == {
            ("firing", False): 1,
            ("firing", True): 2,
            ("not_firing", False): 1,
            ("broken", False): 1,
        }
        assert len(logs.alerts) == len(PlatformAlertState) * 2
        insight = by_source[SourceKind.INSIGHT]
        assert {(c.enabled, c.owner.value): c.count for c in insight.configurations if c.count} == {(True, "source"): 1}
        assert {(a.state.value, a.muted): a.count for a in insight.alerts if a.count} == {("firing", False): 1}

    def test_a_slow_count_is_canceled_by_the_statement_timeout(self) -> None:
        def slow_count(
            execute: Callable[[str, object, bool, dict[str, object]], object],
            sql: str,
            params: object,
            many: bool,
            context: dict[str, object],
        ) -> object:
            if "COUNT(" in sql:
                return execute("SELECT pg_sleep(5)", None, False, context)
            return execute(sql, params, many, context)

        with (
            patch("products.alerts_platform.backend.logic.inventory.INVENTORY_STATEMENT_TIMEOUT_MS", 50),
            connection.execute_wrapper(slow_count),
            pytest.raises(OperationalError) as caught,
        ):
            count_inventory(NOW)

        assert getattr(caught.value.__cause__, "sqlstate", None) == "57014"


def test_push_replaces_the_group_with_the_dashboard_labels() -> None:
    inventory = SourceInventory(
        source=SourceKind.LOGS,
        configurations=(
            ConfigurationCount(enabled=True, owner=PlatformAlertOwner.SOURCE, count=3),
            ConfigurationCount(enabled=True, owner=PlatformAlertOwner.PLATFORM, count=2),
            ConfigurationCount(enabled=False, owner=PlatformAlertOwner.SOURCE, count=1),
        ),
        alerts=(AlertCount(state=PlatformAlertState.FIRING, muted=True, count=2),),
    )

    with patch("posthog.metrics.push_registry") as push:
        push_inventory([inventory])

    assert push.call_args.args[0] == "alerts_platform_inventory"
    assert push.call_args.kwargs == {"replace_group": True, "timeout": 5}
    registry = push.call_args.args[1]
    configurations = {
        (labels["enabled"], labels["owner"]): value
        for labels, value in (
            (sample.labels, sample.value)
            for metric in registry.collect()
            if metric.name == "alerts_platform_configurations"
            for sample in metric.samples
        )
    }
    assert configurations == {("true", "source"): 3, ("true", "platform"): 2, ("false", "source"): 1}
    assert (
        registry.get_sample_value("alerts_platform_alerts", {"source": "logs", "state": "firing", "muted": "true"}) == 2
    )
