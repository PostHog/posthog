from datetime import UTC, datetime

import pytest

from asgiref.sync import sync_to_async
from freezegun import freeze_time
from temporalio.testing import ActivityEnvironment

from posthog.schema import AlertCalculationInterval

from posthog.models import Team
from posthog.temporal.alerts.activities import retrieve_due_alerts
from posthog.temporal.alerts.types import ScheduleDueAlertChecksWorkflowInputs
from posthog.temporal.tests.test_alerts_activities import _create_alert


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_retrieve_due_alerts_caps_each_team_within_a_schedule_run(ateam: Team) -> None:
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
        ScheduleDueAlertChecksWorkflowInputs(max_alerts_per_run=4, max_alerts_per_team_per_run=1),
    )

    assert len(alerts) == 2
    assert {alert.team_id for alert in alerts} == {ateam.id, other_team.id}


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

    with freeze_time("2026-09-10T12:00:00Z"):
        alerts = await ActivityEnvironment().run(
            retrieve_due_alerts,
            ScheduleDueAlertChecksWorkflowInputs(max_alerts_per_run=2, max_alerts_per_team_per_run=2),
        )

    assert len(alerts) == 2
    assert str(old_daily_alert.id) in {alert.alert_id for alert in alerts}


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_retrieve_due_alerts_keeps_active_cohort_in_team_allowance(ateam: Team) -> None:
    due_alerts = [
        await _create_alert(
            ateam,
            next_check_at=datetime(2026, 9, 10, 11, minute, tzinfo=UTC),
        )
        for minute in range(3)
    ]
    inputs = ScheduleDueAlertChecksWorkflowInputs(max_alerts_per_run=2, max_alerts_per_team_per_run=2)

    with freeze_time("2026-09-10T12:00:00Z"):
        first_sweep = await ActivityEnvironment().run(retrieve_due_alerts, inputs)
        second_sweep = await ActivityEnvironment().run(retrieve_due_alerts, inputs)

    expected_ids = {str(alert.id) for alert in due_alerts[:2]}
    assert {alert.alert_id for alert in first_sweep} == expected_ids
    assert {alert.alert_id for alert in second_sweep} == expected_ids
