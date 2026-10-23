from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import OperationalError, connection

from posthog.models import Team

from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.alerts_platform.backend.logic.inventory import count_source_inventory
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration

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
        snooze_until: datetime | None = None,
        alerts: list[tuple[str, datetime | None]] | None = None,
    ) -> None:
        configuration = PlatformAlertConfiguration.objects.unscoped().create(
            team=team,
            name="alert",
            enabled=enabled,
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

    def test_counts_one_source_across_teams_split_by_state_and_mute(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        self._configuration(
            self.team,
            alerts=[("firing", None), ("firing", LATER), ("not_firing", EARLIER)],
        )
        self._configuration(other_team, snooze_until=LATER, alerts=[("firing", None)])
        self._configuration(other_team, alerts=[("broken", None)])
        self._configuration(other_team, enabled=False, alerts=[("firing", None)])
        self._configuration(self.team, source=SourceKind.INSIGHT, alerts=[("firing", None)])

        inventory = count_source_inventory(SourceKind.LOGS, NOW)

        assert inventory.source == SourceKind.LOGS
        assert {(c.enabled, c.count) for c in inventory.configurations} == {(True, 3), (False, 1)}
        assert {(a.state.value, a.muted): a.count for a in inventory.alerts if a.count} == {
            ("firing", False): 1,
            ("firing", True): 2,
            ("not_firing", False): 1,
            ("broken", False): 1,
        }
        assert len(inventory.alerts) == len(PlatformAlertState) * 2

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
            count_source_inventory(SourceKind.LOGS, NOW)

        assert getattr(caught.value.__cause__, "sqlstate", None) == "57014"
