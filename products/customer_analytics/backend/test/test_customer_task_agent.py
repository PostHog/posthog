from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from products.customer_analytics.backend.logic import customer_task_agent
from products.customer_analytics.backend.logic.customer_task_agent import REPORT_GRACE, RUN_LEAD, sweep_agent_tasks
from products.customer_analytics.backend.models import CustomerTask, CustomerTaskActivity
from products.workflows.backend.facade.api import WorkflowDTO, WorkflowInvalid, WorkflowScheduleDTO

WORKFLOW_ID = "0199f0a0-0000-7000-8000-000000000001"
SCHEDULE_ID = "0199f0a0-0000-7000-8000-000000000002"


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class TestCustomerTaskAgentSweep(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now().replace(microsecond=0)
        self.create_workflow = self._patch(
            "create_workflow",
            return_value=WorkflowDTO(id=WORKFLOW_ID, name="PostHog task: Draft the renewal brief", status="active"),
        )
        self.create_schedule = self._patch(
            "create_workflow_schedule",
            side_effect=lambda **kwargs: WorkflowScheduleDTO(
                id=SCHEDULE_ID,
                workflow_id=str(kwargs["workflow_id"]),
                status="active",
                starts_at=kwargs["starts_at"],
                next_run_at=None,
            ),
        )
        self.archive_workflow = self._patch("archive_workflow", return_value=None)

    def _patch(self, name: str, **kwargs: Any) -> MagicMock:
        patcher = patch.object(customer_task_agent.workflows, name, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _task(self, *, due_at: datetime | None = None, agent: dict[str, Any] | None = None) -> CustomerTask:
        return CustomerTask.objects.for_team(self.team.id).create(
            team=self.team,
            name="Draft the renewal brief",
            description="Summarize usage and propose the renewal terms.",
            assigned_to_agent=True,
            due_at=due_at,
            properties={
                "agent": {"assigned_by_id": self.user.id, "assigned_at": "2026-09-01T09:00:00Z", **(agent or {})}
            },
        )

    def _activities(self, task: CustomerTask, activity_type: str) -> list[CustomerTaskActivity]:
        return list(CustomerTaskActivity.objects.for_team(self.team.id).filter(task=task, activity_type=activity_type))

    def test_sweep_creates_a_one_shot_loop_for_the_due_date(self) -> None:
        due_at = self.now + timedelta(days=2)
        task = self._task(due_at=due_at)

        counts = sweep_agent_tasks(now=self.now)

        assert counts == {"provisioned": 1, "expired": 0, "archived": 0}
        self.create_workflow.assert_called_once()
        kwargs = self.create_workflow.call_args.kwargs
        assert kwargs["team_id"] == self.team.id
        assert kwargs["user_id"] == self.user.id
        payload = kwargs["data"]
        assert payload["status"] == "active"
        assert payload["origin_product"] == "loops"
        assert [action["id"] for action in payload["actions"]] == ["trigger", "create_task", "report", "exit"]
        prompt = payload["actions"][1]["config"]["inputs"]["prompt"]["value"]
        assert str(task.id) in prompt
        # The description is read through the API at run time, never written into the instructions.
        assert "renewal terms" not in prompt
        assert payload["actions"][1]["config"]["inputs"]["posthog_mcp_scopes"]["value"] == "read_only"
        report_inputs = payload["actions"][2]["config"]["inputs"]
        assert report_inputs["customer_task_id"]["value"] == str(task.id)
        assert report_inputs["report"]["value"] == "{variables.task_final_message}"
        assert report_inputs["outcome"]["value"] == "{variables.outcome}"
        assert {variable["key"]: variable["default"] for variable in payload["variables"]} == {
            "task_final_message": "",
            "outcome": "needs_human",
        }
        self.create_schedule.assert_called_once_with(
            team_id=self.team.id,
            user_id=self.user.id,
            workflow_id=UUID(WORKFLOW_ID),
            rrule="FREQ=DAILY;COUNT=1",
            starts_at=due_at,
        )
        task.refresh_from_db()
        assert task.assigned_to_agent is True
        assert task.properties["agent"]["hog_flow_id"] == WORKFLOW_ID
        assert task.properties["agent"]["schedule_id"] == SCHEDULE_ID
        assert task.properties["agent"]["scheduled_for"] == _iso(due_at)
        assert len(self._activities(task, "agent_scheduled")) == 1

        assert sweep_agent_tasks(now=self.now) == {"provisioned": 0, "expired": 0, "archived": 0}
        self.create_workflow.assert_called_once()

    @parameterized.expand(
        [
            ("no due date", None),
            ("a past due date", timedelta(days=-1)),
            ("a due date within the lead", timedelta(minutes=1)),
        ]
    )
    def test_sweep_runs_the_loop_soon_when_the_due_date_cannot_be_used(
        self, _name: str, offset: timedelta | None
    ) -> None:
        self._task(due_at=self.now + offset if offset is not None else None)

        sweep_agent_tasks(now=self.now)

        assert self.create_schedule.call_args.kwargs["starts_at"] == self.now + RUN_LEAD

    def test_a_loop_that_cannot_be_created_hands_the_task_back(self) -> None:
        self.create_workflow.side_effect = WorkflowInvalid({"actions": ["Unknown template."]})
        task = self._task()

        counts = sweep_agent_tasks(now=self.now)

        assert counts["provisioned"] == 1
        self.create_schedule.assert_not_called()
        task.refresh_from_db()
        assert task.assigned_to_agent is False
        assert task.assigned_to == self.user
        assert task.status == "open"
        assert "Unknown template" in task.properties["agent"]["failure"]
        assert "hog_flow_id" not in task.properties["agent"]
        failures = self._activities(task, "agent_failed")
        assert len(failures) == 1
        assert {change["field"] for change in failures[0].changes} == {
            "agent_failure",
            "assigned_to",
            "assigned_to_agent",
        }

    def test_a_schedule_that_cannot_be_created_archives_the_loop(self) -> None:
        self.create_schedule.side_effect = WorkflowInvalid({"rrule": ["Schedule produces no future occurrences."]})
        task = self._task()

        sweep_agent_tasks(now=self.now)

        self.archive_workflow.assert_called_once_with(
            team_id=self.team.id, user_id=self.user.id, workflow_id=UUID(WORKFLOW_ID)
        )
        task.refresh_from_db()
        assert task.assigned_to_agent is False
        assert len(self._activities(task, "agent_failed")) == 1

    def test_sweep_hands_back_a_task_whose_loop_never_reported(self) -> None:
        silent = self._task(
            agent={
                "hog_flow_id": WORKFLOW_ID,
                "schedule_id": SCHEDULE_ID,
                "scheduled_for": _iso(self.now - REPORT_GRACE - timedelta(minutes=1)),
            }
        )
        pending = self._task(
            agent={
                "hog_flow_id": str(uuid4()),
                "schedule_id": str(uuid4()),
                "scheduled_for": _iso(self.now - timedelta(hours=1)),
            }
        )

        counts = sweep_agent_tasks(now=self.now)

        assert counts["expired"] == 1
        silent.refresh_from_db()
        assert silent.assigned_to_agent is False
        assert silent.assigned_to == self.user
        assert len(self._activities(silent, "agent_failed")) == 1
        pending.refresh_from_db()
        assert pending.assigned_to_agent is True
        # The same pass archives the loop the task no longer waits on.
        assert counts["archived"] == 1
        self.archive_workflow.assert_called_once_with(
            team_id=self.team.id, user_id=self.user.id, workflow_id=UUID(WORKFLOW_ID)
        )
        silent.refresh_from_db()
        assert silent.properties["agent"]["loop_archived_at"]

    @parameterized.expand([("reported", {"outcome": "completed"}, True), ("taken back", {}, False)])
    def test_sweep_archives_the_loop_once_the_task_is_settled(
        self, _name: str, agent: dict[str, Any], assigned_to_agent: bool
    ) -> None:
        task = self._task(
            agent={"hog_flow_id": WORKFLOW_ID, "schedule_id": SCHEDULE_ID, "scheduled_for": _iso(self.now), **agent}
        )
        CustomerTask.objects.for_team(self.team.id).filter(id=task.id).update(assigned_to_agent=assigned_to_agent)

        assert sweep_agent_tasks(now=self.now)["archived"] == 1

        self.archive_workflow.assert_called_once_with(
            team_id=self.team.id, user_id=self.user.id, workflow_id=UUID(WORKFLOW_ID)
        )
        task.refresh_from_db()
        assert task.properties["agent"]["loop_archived_at"]
        assert sweep_agent_tasks(now=self.now)["archived"] == 0
        self.archive_workflow.assert_called_once()
