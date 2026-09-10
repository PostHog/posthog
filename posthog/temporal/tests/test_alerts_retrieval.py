import pytest

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

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
