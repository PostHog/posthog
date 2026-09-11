from collections import Counter
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
async def test_retrieve_due_alerts_fills_unused_capacity_after_each_team_gets_fair_share(ateam: Team) -> None:
    for _ in range(2):
        await _create_alert(ateam)

    other_team = await sync_to_async(Team.objects.create)(
        organization_id=ateam.organization_id,
        project_id=ateam.project_id,
        name="Other team",
    )
    for _ in range(2):
        await _create_alert(other_team)

    alerts = await ActivityEnvironment().run(
        retrieve_due_alerts,
        ScheduleDueAlertChecksWorkflowInputs(max_alerts_per_run=4, team_fair_share_per_run=1),
    )

    assert len(alerts) == 4
    assert {alert.team_id for alert in alerts} == {ateam.id, other_team.id}


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_retrieve_due_alerts_prioritizes_each_team_before_overflow(ateam: Team) -> None:
    for _ in range(3):
        await _create_alert(ateam)

    other_team = await sync_to_async(Team.objects.create)(
        organization_id=ateam.organization_id,
        project_id=ateam.project_id,
        name="Other team",
    )
    await _create_alert(other_team)

    alerts = await ActivityEnvironment().run(
        retrieve_due_alerts,
        ScheduleDueAlertChecksWorkflowInputs(max_alerts_per_run=2, team_fair_share_per_run=1),
    )

    assert len(alerts) == 2
    assert {alert.team_id for alert in alerts} == {ateam.id, other_team.id}


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_retrieve_due_alerts_truncates_in_rank_rounds_across_teams(ateam: Team) -> None:
    teams = [
        ateam,
        await sync_to_async(Team.objects.create)(
            organization_id=ateam.organization_id,
            project_id=ateam.project_id,
            name="Second team",
        ),
        await sync_to_async(Team.objects.create)(
            organization_id=ateam.organization_id,
            project_id=ateam.project_id,
            name="Third team",
        ),
    ]
    for team in teams:
        for _ in range(3):
            await _create_alert(team)

    alerts = await ActivityEnvironment().run(
        retrieve_due_alerts,
        ScheduleDueAlertChecksWorkflowInputs(max_alerts_per_run=5, team_fair_share_per_run=3),
    )

    assert len(alerts) == 5
    assert sorted(Counter(alert.team_id for alert in alerts).values()) == [1, 2, 2]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_retrieve_due_alerts_promotes_aged_alerts_over_fresh_high_frequency_alerts(ateam: Team) -> None:
    old_daily_alert = await _create_alert(
        ateam,
        calculation_interval=AlertCalculationInterval.DAILY.value,
        next_check_at=datetime(2026, 9, 10, 11, 40, tzinfo=UTC),
    )
    for _ in range(2):
        await _create_alert(
            ateam,
            calculation_interval=AlertCalculationInterval.REAL_TIME.value,
            next_check_at=datetime(2026, 9, 10, 11, 59, tzinfo=UTC),
        )

    with time_machine.travel("2026-09-10T12:00:00Z", tick=False):
        alerts = await ActivityEnvironment().run(
            retrieve_due_alerts,
            ScheduleDueAlertChecksWorkflowInputs(max_alerts_per_run=2, team_fair_share_per_run=2),
        )

    assert len(alerts) == 2
    assert str(old_daily_alert.id) in {alert.alert_id for alert in alerts}


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

    expected_ids = {str(alert.id) for alert in due_alerts[:2]}
    assert {alert.alert_id for alert in first_sweep} == expected_ids
    assert {alert.alert_id for alert in second_sweep} == expected_ids


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
