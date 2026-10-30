import uuid
import logging
import dataclasses
from datetime import timedelta

import pytest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Organization, Team, User
from posthog.temporal.health_checks import activities as health_check_activities
from posthog.temporal.health_checks.activities import build_team_id_page
from posthog.temporal.health_checks.models import BatchResult, HealthCheckWorkflowInputs, TeamIdPage
from posthog.temporal.health_checks.workflows import HealthCheckWorkflow

PAGES = {
    0: TeamIdPage(team_ids=[1, 2, 3], next_after_team_id=3),
    3: TeamIdPage(team_ids=[4, 5], next_after_team_id=5),
    5: TeamIdPage(team_ids=[6], next_after_team_id=None),
}
processed_team_ids: list[int] = []
pushed_totals: list[dict] = []


@activity.defn(name="get_team_id_page")
async def fake_get_team_id_page(inputs: HealthCheckWorkflowInputs, after_team_id: int) -> TeamIdPage:
    return PAGES[after_team_id]


@activity.defn(name="run_health_check_batch")
async def fake_run_health_check_batch(team_ids: list[int], kind: str, dry_run: bool) -> dict:
    processed_team_ids.extend(team_ids)
    return dataclasses.asdict(BatchResult(batch_size=len(team_ids), teams_healthy=len(team_ids)))


@activity.defn(name="push_health_check_metrics_activity")
async def fake_push_health_check_metrics(kind: str, totals_dict: dict, success: bool) -> None:
    pushed_totals.append(totals_dict)


class TestHealthCheckWorkflow:
    @parameterized.expand([("single_run", False), ("continue_as_new_every_page", True)])
    @pytest.mark.asyncio
    async def test_every_team_runs_once_and_the_totals_cover_the_whole_run(self, _name, continue_as_new):
        logging.getLogger("temporalio.workflow").setLevel(logging.INFO)
        logging.getLogger("temporalio.activity").setLevel(logging.INFO)
        processed_team_ids.clear()
        pushed_totals.clear()
        task_queue = str(uuid.uuid4())

        with patch.object(workflow.Info, "is_continue_as_new_suggested", return_value=continue_as_new):
            async with await WorkflowEnvironment.start_time_skipping() as env:
                async with Worker(
                    env.client,
                    task_queue=task_queue,
                    workflows=[HealthCheckWorkflow],
                    activities=[fake_get_team_id_page, fake_run_health_check_batch, fake_push_health_check_metrics],
                    workflow_runner=UnsandboxedWorkflowRunner(),
                ):
                    result = await env.client.execute_workflow(
                        HealthCheckWorkflow.run,
                        HealthCheckWorkflowInputs(name="check", kind="check", batch_size=2, max_concurrent=2),
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                        execution_timeout=timedelta(minutes=5),
                    )

        assert sorted(processed_team_ids) == [1, 2, 3, 4, 5, 6]

        assert len(pushed_totals) == 1
        assert pushed_totals[0]["batch_size"] == 6
        assert pushed_totals[0]["teams_healthy"] == 6
        assert result["total_teams"] == 6
        assert result["batches"] == 4


@pytest.mark.django_db
def test_team_id_pages_visit_each_recently_active_team_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_check_activities, "BATCHES_PER_TEAM_ID_PAGE", 2)
    active_org = Organization.objects.create(name="active")
    inactive_org = Organization.objects.create(name="inactive")
    for org, last_login in ((active_org, timezone.now()), (inactive_org, timezone.now() - timedelta(days=60))):
        user = User.objects.create_and_join(org, f"{org.name}@example.com", None)
        User.objects.filter(id=user.id).update(last_login=last_login)
    active_team_ids = [Team.objects.create(organization=active_org).id for _ in range(2)]
    Team.objects.create(organization=inactive_org)
    active_team_ids += [Team.objects.create(organization=active_org).id for _ in range(3)]
    inputs = HealthCheckWorkflowInputs(name="check", kind="check", batch_size=1, active_since_days=30)

    visited: list[int] = []
    after_team_id: int | None = 0
    while after_team_id is not None:
        page = build_team_id_page(inputs, after_team_id)
        visited += page.team_ids
        after_team_id = page.next_after_team_id

    assert visited == active_team_ids
