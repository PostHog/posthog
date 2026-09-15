from datetime import UTC, datetime

import pytest
import time_machine
from unittest.mock import MagicMock, call, patch

from asgiref.sync import sync_to_async
from temporalio.common import MetricCounter, MetricMeter
from temporalio.testing import ActivityEnvironment

from posthog.schema import AlertCalculationInterval

from posthog.models import Team
from posthog.temporal.alerts.activities import retrieve_due_alerts
from posthog.temporal.alerts.types import ScheduleDueAlertChecksWorkflowInputs
from posthog.temporal.tests.test_alerts_activities import _create_alert


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    ("alerts_per_team", "max_alerts_per_run", "team_fair_share_per_run", "expected_team_order"),
    [
        pytest.param([2, 2], 4, 1, [0, 1, 0, 1], id="overflow-fills-unused-capacity"),
        pytest.param([3, 1], 2, 1, [0, 1], id="fair-share-precedes-overflow"),
        pytest.param([3, 3, 3], 5, 3, [0, 1, 2, 0, 1], id="truncation-uses-rank-rounds"),
    ],
)
async def test_retrieve_due_alerts_orders_fair_share_before_overflow(
    ateam: Team,
    alerts_per_team: list[int],
    max_alerts_per_run: int,
    team_fair_share_per_run: int,
    expected_team_order: list[int],
) -> None:
    teams = [ateam]
    for team_index in range(1, len(alerts_per_team)):
        teams.append(
            await sync_to_async(Team.objects.create)(
                organization_id=ateam.organization_id,
                project_id=ateam.project_id,
                name=f"Team {team_index}",
            )
        )

    for team, alert_count in zip(teams, alerts_per_team, strict=True):
        for _ in range(alert_count):
            await _create_alert(team)

    alerts = await ActivityEnvironment().run(
        retrieve_due_alerts,
        ScheduleDueAlertChecksWorkflowInputs(
            max_alerts_per_run=max_alerts_per_run,
            team_fair_share_per_run=team_fair_share_per_run,
        ),
    )

    team_index_by_id = {team.id: index for index, team in enumerate(teams)}
    assert [team_index_by_id[alert.team_id] for alert in alerts] == expected_team_order


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_retrieve_due_alerts_applies_the_documented_order_within_each_team(ateam: Team) -> None:
    alert_specs = [
        ("fresh_daily_tie_lower_id", AlertCalculationInterval.DAILY, datetime(2026, 9, 10, 11, 47, tzinfo=UTC)),
        ("fresh_hourly", AlertCalculationInterval.HOURLY, datetime(2026, 9, 10, 11, 46, tzinfo=UTC)),
        ("aged_real_time", AlertCalculationInterval.REAL_TIME, datetime(2026, 9, 10, 11, 40, tzinfo=UTC)),
        ("fresh_daily_earlier", AlertCalculationInterval.DAILY, datetime(2026, 9, 10, 11, 46, tzinfo=UTC)),
        ("never_checked", AlertCalculationInterval.DAILY, None),
        ("fresh_real_time", AlertCalculationInterval.REAL_TIME, datetime(2026, 9, 10, 11, 59, tzinfo=UTC)),
        ("aged_daily_oldest", AlertCalculationInterval.DAILY, datetime(2026, 9, 10, 11, 30, tzinfo=UTC)),
        ("fresh_15_minutes", AlertCalculationInterval.EVERY_15_MINUTES, datetime(2026, 9, 10, 11, 58, tzinfo=UTC)),
        ("fresh_daily_tie_higher_id", AlertCalculationInterval.DAILY, datetime(2026, 9, 10, 11, 47, tzinfo=UTC)),
    ]
    alert_label_by_id: dict[str, str] = {}
    for label, calculation_interval, next_check_at in alert_specs:
        alert = await _create_alert(
            ateam,
            calculation_interval=calculation_interval.value,
            next_check_at=next_check_at,
        )
        alert_label_by_id[str(alert.id)] = label

    with time_machine.travel("2026-09-10T12:00:00Z", tick=False):
        alerts = await ActivityEnvironment().run(
            retrieve_due_alerts,
            ScheduleDueAlertChecksWorkflowInputs(
                max_alerts_per_run=len(alert_specs),
                team_fair_share_per_run=len(alert_specs),
            ),
        )

    assert [alert_label_by_id[alert.alert_id] for alert in alerts] == [
        "never_checked",
        "aged_daily_oldest",
        "aged_real_time",
        "fresh_real_time",
        "fresh_15_minutes",
        "fresh_hourly",
        "fresh_daily_earlier",
        "fresh_daily_tie_lower_id",
        "fresh_daily_tie_higher_id",
    ]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_retrieve_due_alerts_keeps_active_cohort_in_fair_share(ateam: Team) -> None:
    due_alerts = [
        await _create_alert(
            ateam,
            next_check_at=datetime(2026, 9, 10, 11, minute, tzinfo=UTC),
        )
        for minute in range(3)
    ]
    inputs = ScheduleDueAlertChecksWorkflowInputs(max_alerts_per_run=2, team_fair_share_per_run=2)

    with time_machine.travel("2026-09-10T12:00:00Z", tick=False):
        first_sweep = await ActivityEnvironment().run(retrieve_due_alerts, inputs)
        second_sweep = await ActivityEnvironment().run(retrieve_due_alerts, inputs)

    expected_ids = [str(alert.id) for alert in due_alerts[:2]]
    assert [alert.alert_id for alert in first_sweep] == expected_ids
    assert [alert.alert_id for alert in second_sweep] == expected_ids


@pytest.mark.asyncio
async def test_retrieve_due_alerts_records_capacity_and_selected_alert_counters() -> None:
    meter = MagicMock(spec=MetricMeter)
    capacity_counter = MagicMock(spec=MetricCounter)
    selected_counter = MagicMock(spec=MetricCounter)
    counters = {
        "insight_alert_scheduler_capacity": capacity_counter,
        "insight_alert_scheduler_alerts_selected": selected_counter,
    }
    meter.create_counter.side_effect = lambda name, description: counters[name]
    environment = ActivityEnvironment()

    async def fake_get_alerts() -> list[MagicMock]:
        return [MagicMock()] * 9

    with (
        patch(
            "posthog.temporal.alerts.activities.database_sync_to_async",
            return_value=MagicMock(return_value=fake_get_alerts),
        ),
        patch("posthog.temporal.alerts.activities.get_metric_meter", return_value=meter),
    ):
        for max_alerts_per_run in (11, 10, 9):
            await environment.run(
                retrieve_due_alerts,
                ScheduleDueAlertChecksWorkflowInputs(max_alerts_per_run=max_alerts_per_run),
            )

    assert [metric_call.args[0] for metric_call in meter.create_counter.call_args_list] == [
        "insight_alert_scheduler_capacity",
        "insight_alert_scheduler_alerts_selected",
        "insight_alert_scheduler_capacity",
        "insight_alert_scheduler_alerts_selected",
        "insight_alert_scheduler_capacity",
        "insight_alert_scheduler_alerts_selected",
    ]
    assert capacity_counter.add.call_args_list == [call(11), call(10), call(9)]
    assert selected_counter.add.call_args_list == [call(9), call(9), call(9)]
    meter.with_additional_attributes.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_due_alerts_succeeds_when_metric_recording_fails() -> None:
    expected_alerts = [MagicMock()]

    async def fake_get_alerts() -> list[MagicMock]:
        return expected_alerts

    with (
        patch(
            "posthog.temporal.alerts.activities.database_sync_to_async",
            return_value=MagicMock(return_value=fake_get_alerts),
        ),
        patch(
            "posthog.temporal.alerts.activities.get_metric_meter",
            side_effect=RuntimeError("metrics backend unavailable"),
        ),
    ):
        alerts = await ActivityEnvironment().run(retrieve_due_alerts)

    assert alerts == expected_alerts
