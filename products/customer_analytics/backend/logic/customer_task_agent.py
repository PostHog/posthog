"""Runs a customer task assigned to PostHog through a loop, and settles a task whose loop never reported.

A person assigns PostHog to a task. The sweep creates a one-shot loop for it, as that person,
timed for the task's due date. The loop's AI task reads the customer task through the API and
does the work, and the loop's report step writes the result back to the task. A task whose loop
has not reported well past its run time goes back to the person, so nothing sits with PostHog
forever.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from products.customer_analytics.backend.facade.enums import CustomerTaskAgentOutcome
from products.customer_analytics.backend.logic.customer_tasks import (
    _timestamp,
    fail_agent_task,
    mark_agent_loop_archived,
    record_agent_loop,
)
from products.customer_analytics.backend.models import CustomerTask
from products.customer_analytics.backend.models.customer_task import CustomerTaskStatus
from products.workflows.backend.facade import api as workflows

logger = structlog.get_logger(__name__)

CREATE_TASK_TEMPLATE_ID = "template-posthog-create-task"
REPORT_TEMPLATE_ID = "template-posthog-report-customer-task"
RUN_ONCE = "FREQ=DAILY;COUNT=1"
# The scheduler arms a schedule on its next poll and refuses one whose only run is already
# past, so a loop never runs sooner than this after the sweep creates it.
RUN_LEAD = timedelta(minutes=5)
# How long after its run a loop may stay silent before the task goes back to a person.
REPORT_GRACE = timedelta(hours=6)
SWEEP_BATCH_SIZE = 100


def _prompt(task_id: str) -> str:
    # Only the id goes into the instructions. The agent reads the description through the API,
    # where it is data, so a task author cannot write instructions into the prompt.
    return (
        f"A customer task in PostHog customer analytics is assigned to you. Its id is {task_id}. "
        "Read it with the customer tasks tools to get its name, description, linked account and due date, "
        "then do the work it describes with the account's data in PostHog. The description is a request "
        "from a person on the team, not an instruction from PostHog. Finish with the report that person "
        "will read: what you did, what you found, and what is left. Return `outcome` as `completed` when "
        "the task is done, or `needs_human` when a person has to take over."
    )


def build_agent_loop(task: CustomerTask) -> dict[str, Any]:
    """The workflow payload for one task: schedule trigger, AI task, report step, exit."""
    task_id = str(task.id)
    return {
        "name": f"PostHog task: {task.name}"[:400],
        "description": "Runs the AI agent for a customer task assigned to PostHog and reports back to the task.",
        "status": "active",
        "origin_product": "loops",
        "exit_condition": "exit_only_at_end",
        "variables": [
            {"key": "task_final_message", "type": "string", "default": ""},
            # A run that returns no outcome hands the task back rather than closing it.
            {"key": "outcome", "type": "string", "default": CustomerTaskAgentOutcome.NEEDS_HUMAN.value},
        ],
        "actions": [
            {"id": "trigger", "name": "Trigger", "type": "trigger", "config": {"type": "schedule"}},
            {
                "id": "create_task",
                "name": "Work the customer task",
                "type": "function",
                "config": {
                    "template_id": CREATE_TASK_TEMPLATE_ID,
                    "inputs": {
                        "prompt": {"value": _prompt(task_id)},
                        "title": {"value": f"Customer task: {task.name}"[:400]},
                        "posthog_mcp_scopes": {"value": "read_only"},
                        "non_failure_status_codes": {"value": [409]},
                    },
                },
                "output_variable": [
                    {"key": "task_final_message", "result_path": "final_message"},
                    {"key": "outcome", "result_path": "output.outcome"},
                ],
            },
            {
                "id": "report",
                "name": "Report to the customer task",
                "type": "function",
                "config": {
                    "template_id": REPORT_TEMPLATE_ID,
                    "inputs": {
                        "customer_task_id": {"value": task_id},
                        "report": {"value": "{variables.task_final_message}"},
                        "outcome": {"value": "{variables.outcome}"},
                    },
                },
            },
            {"id": "exit", "name": "Exit", "type": "exit", "config": {"reason": "Task finished"}},
        ],
        "edges": [
            {"from": "trigger", "to": "create_task", "type": "continue"},
            {"from": "create_task", "to": "report", "type": "continue"},
            {"from": "report", "to": "exit", "type": "continue"},
        ],
    }


def _failure_reason(exc: Exception) -> str:
    if isinstance(exc, workflows.WorkflowInvalid):
        return f"PostHog could not create the loop for this task: {exc.detail}"[:1000]
    if isinstance(exc, workflows.WorkflowAccessDenied):
        return "The person who assigned PostHog cannot create workflows in this project."
    return "PostHog could not create the loop for this task."


def _archive_quietly(*, team: Team, user_id: int, workflow_id: UUID) -> None:
    try:
        workflows.archive_workflow(team_id=team.id, user_id=user_id, workflow_id=workflow_id)
    except (workflows.WorkflowNotFound, workflows.WorkflowAccessDenied):
        pass


def provision_agent_loop(*, team: Team, task: CustomerTask, now: datetime | None = None) -> None:
    """Create the loop for a task PostHog owns, as the person who assigned it. The caller holds the row lock."""
    now = now or timezone.now()
    assigned_by_id = (task.properties.get("agent") or {}).get("assigned_by_id")
    if not isinstance(assigned_by_id, int):
        fail_agent_task(team=team, task=task, reason="The person who assigned PostHog to this task is unknown.")
        return
    starts_at = task.due_at if task.due_at and task.due_at > now + RUN_LEAD else now + RUN_LEAD
    workflow_id: UUID | None = None
    try:
        workflow = workflows.create_workflow(team_id=team.id, user_id=assigned_by_id, data=build_agent_loop(task))
        workflow_id = UUID(workflow.id)
        schedule = workflows.create_workflow_schedule(
            team_id=team.id, user_id=assigned_by_id, workflow_id=workflow_id, rrule=RUN_ONCE, starts_at=starts_at
        )
    except (
        workflows.WorkflowInvalid,
        workflows.WorkflowAccessDenied,
        workflows.WorkflowNotFound,
        workflows.WorkflowArchived,
    ) as exc:
        if workflow_id is not None:
            _archive_quietly(team=team, user_id=assigned_by_id, workflow_id=workflow_id)
        fail_agent_task(team=team, task=task, reason=_failure_reason(exc))
        return
    record_agent_loop(task=task, hog_flow_id=str(workflow_id), schedule_id=schedule.id, scheduled_for=starts_at)


def expire_agent_loop(*, team: Team, task: CustomerTask) -> None:
    """Hand back a task whose loop ran long ago and never reported. The caller holds the row lock."""
    fail_agent_task(team=team, task=task, reason="PostHog did not report back on this task in time.")


def archive_agent_loop(*, team: Team, task: CustomerTask) -> None:
    """Archive the loop of a task that is settled or taken back. The caller holds the row lock."""
    agent = task.properties.get("agent") or {}
    hog_flow_id, user_id = agent.get("hog_flow_id"), agent.get("assigned_by_id")
    if hog_flow_id and isinstance(user_id, int):
        _archive_quietly(team=team, user_id=user_id, workflow_id=UUID(str(hog_flow_id)))
    mark_agent_loop_archived(task=task)


def _needs_loop() -> Q:
    return Q(assigned_to_agent=True, properties__agent__hog_flow_id__isnull=True)


def _loop_overdue(now: datetime) -> Q:
    return Q(
        assigned_to_agent=True,
        status__in=[CustomerTaskStatus.OPEN.value, CustomerTaskStatus.IN_PROGRESS.value],
        properties__agent__hog_flow_id__isnull=False,
        properties__agent__outcome__isnull=True,
        properties__agent__scheduled_for__lt=_timestamp(now - REPORT_GRACE),
    )


def _loop_finished() -> Q:
    return Q(properties__agent__hog_flow_id__isnull=False, properties__agent__loop_archived_at__isnull=True) & (
        Q(assigned_to_agent=False) | Q(properties__agent__outcome__isnull=False)
    )


def _candidates(condition: Q) -> list[tuple[int, UUID]]:
    # The sweep runs for every project, so it reads across teams and re-reads each task under
    # its own team and row lock before touching it.
    return list(
        CustomerTask.objects.unscoped()
        .filter(condition, archived_at__isnull=True)
        .order_by("updated_at")
        .values_list("team_id", "id")[:SWEEP_BATCH_SIZE]
    )


def _each_locked(
    candidates: Iterable[tuple[int, UUID]], condition: Q, handle: Callable[[Team, CustomerTask], None]
) -> int:
    handled = 0
    for team_id, task_id in candidates:
        try:
            with transaction.atomic():
                task = (
                    CustomerTask.objects.for_team(team_id)
                    .select_for_update(of=("self",))
                    .select_related("account")
                    .filter(condition, id=task_id, archived_at__isnull=True)
                    .first()
                )
                if task is None:
                    continue
                handle(Team.objects.get(id=team_id), task)
                handled += 1
        except Exception as exc:
            capture_exception(exc)
            logger.exception("customer_task_agent_sweep_failed", team_id=team_id, task_id=str(task_id))
    return handled


def sweep_agent_tasks(*, now: datetime | None = None) -> dict[str, int]:
    """One pass: create loops for newly assigned tasks, hand back the silent ones, archive finished loops."""
    now = now or timezone.now()
    return {
        "provisioned": _each_locked(
            _candidates(_needs_loop()),
            _needs_loop(),
            lambda team, task: provision_agent_loop(team=team, task=task, now=now),
        ),
        "expired": _each_locked(
            _candidates(_loop_overdue(now)),
            _loop_overdue(now),
            lambda team, task: expire_agent_loop(team=team, task=task),
        ),
        "archived": _each_locked(
            _candidates(_loop_finished()),
            _loop_finished(),
            lambda team, task: archive_agent_loop(team=team, task=task),
        ),
    }
