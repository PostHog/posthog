from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

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
    OverdueCount,
    SourceInventory,
    count_inventory,
)
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration
from products.alerts_platform.backend.temporal.inventory_metrics import (
    TickScheduleRuns,
    push_inventory,
    push_tick_schedule_runs,
)

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
        check_interval_minutes: int = 5,
        recurrence_unit: str | None = None,
        next_check_at: datetime | None = None,
        check_status: str = "ok",
    ) -> None:
        configuration = PlatformAlertConfiguration.objects.unscoped().create(
            team=team,
            name="alert",
            enabled=enabled,
            owner=owner,
            source_kind=source.value,
            source_config={},
            check_interval_minutes=check_interval_minutes,
            recurrence_unit=recurrence_unit,
            next_check_at=next_check_at,
            check_status=check_status,
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

    def _overdue(self, source: SourceKind = SourceKind.LOGS, owner: str = "platform") -> OverdueCount:
        (inventory,) = (inventory for inventory in count_inventory(NOW) if inventory.source == source)
        (found,) = (count for count in inventory.overdue if count.owner.value == owner)
        return found

    def _scheduled(self, due_ago: timedelta, **fields: Any) -> None:
        fields.setdefault("owner", PlatformAlertOwner.PLATFORM)
        self._configuration(self.team, next_check_at=NOW - due_ago, **fields)

    def test_overdue_counts_configs_past_grace(self) -> None:
        for due_ago in (timedelta(seconds=30), timedelta(minutes=3), timedelta(hours=3)):
            self._scheduled(due_ago, check_interval_minutes=1)

        overdue = self._overdue()

        assert overdue.overdue == 2
        assert overdue.oldest_due_seconds == timedelta(hours=3).total_seconds()

    def test_hourly_config_within_grace_not_overdue(self) -> None:
        self._scheduled(timedelta(minutes=90), check_interval_minutes=60)

        assert self._overdue().overdue == 0

    def test_calendar_config_uses_two_hour_grace(self) -> None:
        self._scheduled(timedelta(minutes=90), check_interval_minutes=1440, recurrence_unit="day")
        assert self._overdue().overdue == 0

        self._scheduled(timedelta(hours=3), check_interval_minutes=1440, recurrence_unit="day")
        assert self._overdue().overdue == 1

    def test_null_next_check_counted_unscheduled(self) -> None:
        self._configuration(self.team, owner=PlatformAlertOwner.PLATFORM, next_check_at=None)

        overdue = self._overdue()

        assert (overdue.unscheduled, overdue.overdue, overdue.oldest_due_seconds) == (1, 0, 0)

    def test_broken_counted_only_as_broken(self) -> None:
        self._scheduled(timedelta(hours=3), check_status="broken")
        self._configuration(self.team, owner=PlatformAlertOwner.PLATFORM, next_check_at=None, check_status="broken")

        overdue = self._overdue()

        assert (overdue.broken, overdue.overdue, overdue.unscheduled, overdue.oldest_due_seconds) == (2, 0, 0, 0)

    def test_disabled_not_counted(self) -> None:
        self._scheduled(timedelta(hours=3), enabled=False)
        self._scheduled(timedelta(hours=3), enabled=False, check_status="broken")
        self._configuration(self.team, owner=PlatformAlertOwner.PLATFORM, enabled=False, next_check_at=None)

        assert self._overdue() == OverdueCount(
            owner=PlatformAlertOwner.PLATFORM, overdue=0, unscheduled=0, oldest_due_seconds=0, broken=0
        )

    def test_overdue_is_split_by_source_and_owner_zeros_included(self) -> None:
        self._scheduled(timedelta(hours=3), source=SourceKind.METRICS)
        self._scheduled(timedelta(hours=3), source=SourceKind.METRICS, owner=PlatformAlertOwner.SOURCE)
        self._scheduled(timedelta(hours=3), source=SourceKind.METRICS, owner=PlatformAlertOwner.SOURCE)

        by_source = {inventory.source: inventory for inventory in count_inventory(NOW)}

        assert {(c.owner.value, c.overdue) for c in by_source[SourceKind.METRICS].overdue} == {
            ("platform", 1),
            ("source", 2),
        }
        assert {(c.owner.value, c.overdue) for c in by_source[SourceKind.LOGS].overdue} == {
            ("platform", 0),
            ("source", 0),
        }

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
        overdue=(
            OverdueCount(
                owner=PlatformAlertOwner.PLATFORM, overdue=4, unscheduled=1, oldest_due_seconds=600.0, broken=2
            ),
        ),
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
    platform = {"source": "logs", "owner": "platform"}
    assert {
        name: registry.get_sample_value(f"alerts_platform_configurations_{name}", platform)
        for name in ("overdue", "unscheduled", "oldest_due_seconds", "broken")
    } == {"overdue": 4, "unscheduled": 1, "oldest_due_seconds": 600.0, "broken": 2}


def test_schedule_runs_push_to_a_group_of_their_own() -> None:
    with patch("posthog.metrics.push_registry") as push:
        push_tick_schedule_runs(TickScheduleRuns(started=120, skipped_overlap=1, missed_catchup=3))

    assert push.call_args.args[0] == "alerts_platform_tick_schedule"
    registry = push.call_args.args[1]
    assert {
        outcome: registry.get_sample_value("alerts_platform_tick_schedule_actions", {"outcome": outcome})
        for outcome in ("started", "skipped_overlap", "missed_catchup")
    } == {"started": 120, "skipped_overlap": 1, "missed_catchup": 3}
