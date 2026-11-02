import uuid
import logging
import dataclasses
from datetime import timedelta

import pytest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from temporalio import activity, workflow
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Organization, Team, User
from posthog.temporal.health_checks import (
    activities as health_check_activities,
    workflows as health_check_workflows,
)
from posthog.temporal.health_checks.activities import build_team_id_page
from posthog.temporal.health_checks.models import BatchResult, HealthCheckWorkflowInputs, TeamIdPage
from posthog.temporal.health_checks.workflows import HealthCheckWorkflow

FIRST_PAGE = TeamIdPage(team_ids=[1, 2, 3], next_after_team_id=3)
PAGES = {
    0: FIRST_PAGE,
    3: TeamIdPage(team_ids=[4, 5], next_after_team_id=5),
    5: TeamIdPage(team_ids=[6], next_after_team_id=None),
}
pages: dict[int, TeamIdPage] = {}
processed_team_ids: list[int] = []
pushed_totals: list[dict] = []


@activity.defn(name="get_team_id_page")
async def fake_get_team_id_page(inputs: HealthCheckWorkflowInputs, after_team_id: int) -> TeamIdPage:
    return pages[after_team_id]


@activity.defn(name="run_health_check_batch")
async def fake_run_health_check_batch(team_ids: list[int], kind: str, dry_run: bool) -> dict:
    processed_team_ids.extend(team_ids)
    return dataclasses.asdict(BatchResult(batch_size=len(team_ids), teams_healthy=len(team_ids)))


@activity.defn(name="push_health_check_metrics_activity")
async def fake_push_health_check_metrics(kind: str, totals_dict: dict, success: bool) -> None:
    pushed_totals.append(totals_dict)


async def _run_workflow(served_pages: dict[int, TeamIdPage]) -> tuple[dict, WorkflowExecutionStatus | None]:
    logging.getLogger("temporalio.workflow").setLevel(logging.INFO)
    logging.getLogger("temporalio.activity").setLevel(logging.INFO)
    pages.clear()
    pages.update(served_pages)
    processed_team_ids.clear()
    pushed_totals.clear()
    task_queue = str(uuid.uuid4())

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[HealthCheckWorkflow],
            activities=[fake_get_team_id_page, fake_run_health_check_batch, fake_push_health_check_metrics],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                HealthCheckWorkflow.run,
                HealthCheckWorkflowInputs(name="check", kind="check", batch_size=2, max_concurrent=2),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=5),
            )
            result = await handle.result()
            first_run = await env.client.get_workflow_handle(handle.id, run_id=handle.first_execution_run_id).describe()
    return result, first_run.status


class TestHealthCheckWorkflow:
    @parameterized.expand(
        [
            ("single_run", False, 10_000, False),
            ("server_suggests_continue_as_new", True, 10_000, True),
            ("history_reaches_the_cap", False, 20, True),
        ]
    )
    @pytest.mark.asyncio
    async def test_every_team_runs_once_and_the_totals_cover_the_whole_run(
        self, _name, continue_as_new_suggested, max_history_events, expect_continued
    ):
        with (
            patch.object(workflow.Info, "is_continue_as_new_suggested", return_value=continue_as_new_suggested),
            patch.object(health_check_workflows, "MAX_HISTORY_EVENTS_PER_RUN", max_history_events),
        ):
            result, first_run_status = await _run_workflow(PAGES)

        assert sorted(processed_team_ids) == [1, 2, 3, 4, 5, 6]

        assert len(pushed_totals) == 1
        assert pushed_totals[0]["batch_size"] == 6
        assert pushed_totals[0]["teams_healthy"] == 6
        assert result["total_teams"] == 6
        assert result["batches"] == 4
        assert (first_run_status == WorkflowExecutionStatus.CONTINUED_AS_NEW) is expect_continued

    @pytest.mark.asyncio
    async def test_kill_switch_stops_the_run_without_reporting_it_complete(self):
        stopped = TeamIdPage(team_ids=[], next_after_team_id=None, stopped_by_kill_switch=True)

        result, _ = await _run_workflow({0: FIRST_PAGE, 3: stopped})

        assert sorted(processed_team_ids) == [1, 2, 3]
        assert pushed_totals == []
        assert result["stopped_by_kill_switch"] is True


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
