from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import OperationalError, connection

from posthog.models import Team

from products.alerts.backend.facade.contracts import SourceKind
from products.alerts.backend.logic.inventory import count_inventory
from products.alerts.backend.models import PlatformAlert, PlatformAlertConfiguration

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)


class TestAlertInventory(BaseTest):
    def _configuration(
        self,
        team: Team,
        *,
        enabled: bool,
        states: list[tuple[str, datetime | None]] | None = None,
        interval: int = 5,
        next_check_at: datetime | None = None,
    ) -> None:
        configuration = PlatformAlertConfiguration.objects.unscoped().create(
            team=team,
            name="alert",
            enabled=enabled,
            source_kind=PlatformAlertConfiguration.SourceKind.LOGS,
            threshold_count=1,
            threshold_operator="above",
            window_minutes=5,
            check_interval_minutes=interval,
            next_check_at=next_check_at,
        )
        for index, (state, snooze_until) in enumerate(states or []):
            PlatformAlert.objects.unscoped().create(
                team=team,
                configuration=configuration,
                grouping_key=str(index),
                state=state,
                snooze_until=snooze_until,
            )

    def test_counts_every_team_split_by_state_and_mute_and_leaves_disabled_alerts_out(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        self._configuration(
            self.team,
            enabled=True,
            states=[("firing", None), ("firing", NOW + timedelta(hours=1)), ("not_firing", NOW - timedelta(hours=1))],
        )
        self._configuration(other_team, enabled=True, states=[("broken", None)])
        self._configuration(other_team, enabled=False, states=[("firing", None)])

        inventory = count_inventory(NOW)

        configurations = {(c.source, c.enabled): c.count for c in inventory.configurations if c.count}
        alerts = {(a.source, a.state, a.muted): a.count for a in inventory.alerts if a.count}
        assert configurations == {("logs", True): 2, ("logs", False): 1}
        assert alerts == {
            ("logs", "firing", False): 1,
            ("logs", "firing", True): 1,
            ("logs", "not_firing", False): 1,
            ("logs", "broken", False): 1,
        }
        assert len(inventory.alerts) == len(SourceKind) * len(PlatformAlert.State) * 2

    def test_counts_enabled_configurations_per_cadence_slot_and_for_the_largest_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        for minutes in (0, 5, 2):
            self._configuration(self.team, enabled=True, next_check_at=NOW + timedelta(minutes=minutes))
        self._configuration(other_team, enabled=True, interval=1, next_check_at=NOW)
        self._configuration(other_team, enabled=True, next_check_at=None)
        self._configuration(other_team, enabled=False, next_check_at=NOW + timedelta(minutes=2))

        inventory = count_inventory(NOW)

        # NOW falls on minute 0 of a 5-minute cadence, so 5 minutes later is slot 0 again.
        assert {(s.source, s.interval_minutes, s.slot): s.count for s in inventory.slots} == {
            ("logs", 1, 0): 1,
            ("logs", 5, 0): 2,
            ("logs", 5, 1): 0,
            ("logs", 5, 2): 1,
            ("logs", 5, 3): 0,
            ("logs", 5, 4): 0,
        }
        assert {(t.source, t.count) for t in inventory.largest_teams} == {("logs", 3)}

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
            patch("products.alerts.backend.logic.inventory.INVENTORY_STATEMENT_TIMEOUT_MS", 50),
            connection.execute_wrapper(slow_count),
            pytest.raises(OperationalError) as caught,
        ):
            count_inventory(NOW)

        assert getattr(caught.value.__cause__, "sqlstate", None) == "57014"
