import dataclasses
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.token_bucket import BucketDecision

from products.cloud_agents.backend.facade.contracts import CallerIdentity
from products.cloud_agents.backend.facade.enums import CallerKind
from products.cloud_agents.backend.models import CloudAgentRun
from products.tasks.backend.facade.cloud_agents import classify_task_run_end
from products.tasks.backend.facade.contracts import (
    CloudAgentPullRequestDTO,
    CloudAgentSessionDTO,
    CloudAgentTaskDTO,
    CloudAgentTaskStateDTO,
    CloudAgentTaskUsageDTO,
    CloudAgentUsageDTO,
    TaskRunBillingDTO,
    TaskRunDTO,
)
from products.tasks.backend.facade.inference import InferenceDecision

FLAG_KEY = "cloud-agents"


class CloudAgentsFlagMixin:
    _flag_patcher: Any

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        self.set_cloud_agents_flag(True)

    def tearDown(self) -> None:
        self._flag_patcher.stop()
        super().tearDown()  # type: ignore[misc]

    def set_cloud_agents_flag(self, enabled: bool) -> None:
        if hasattr(self, "_flag_patcher"):
            self._flag_patcher.stop()
        self._flag_patcher = patch("posthoganalytics.feature_enabled")
        mock = self._flag_patcher.start()
        # Only this flag, so the request does not turn on unrelated flags.
        mock.side_effect = lambda flag_name, *args, **kwargs: enabled if flag_name == FLAG_KEY else False

    def base_url(self) -> str:
        return f"/api/projects/{self.team.id}/cloud_agents"  # type: ignore[attr-defined]


def caller_for(user: Any) -> CallerIdentity:
    return CallerIdentity(user_id=user.id, distinct_id=user.distinct_id, kind=CallerKind.API, billable=True)


LOGIC = "products.cloud_agents.backend.logic"
RUN_CONFIG: dict[str, Any] = {
    "repositories": [{"name": "acme/app", "initial_branch": None}],
    "model": "claude-test-model",
    "reasoning_effort": None,
    "runtime_adapter": "claude",
    "size": "4x16",
    "inference": "posthog",
    "inference_requested": "auto",
    "instructions": None,
    "create_pr": True,
    "idle_minutes": 10,
    "output_schema": None,
    "tags": [],
    "preset_id": None,
}
TERMINAL_TASK_RUN_STATUSES = ("completed", "failed", "cancelled")
PULL_REQUEST_OUTPUT_KEYS = ("pr_url", "pr_urls", "pr_state", "pr_merged")
WAITING_TASK_RUN_STATUSES = ("not_started", "queued")


def task_run_dto(
    *,
    team_id: int,
    task_id: UUID | None = None,
    run_id: UUID | None = None,
    status: str = "queued",
    error_message: str | None = None,
    output: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    completed_at: datetime | None = None,
) -> TaskRunDTO:
    return TaskRunDTO(
        id=run_id or uuid4(),
        task_id=task_id or uuid4(),
        team_id=team_id,
        status=status,
        environment="cloud",
        stage=None,
        branch=None,
        error_message=error_message,
        output=output,
        state=state or {},
        created_at=timezone.now(),
        updated_at=timezone.now(),
        completed_at=completed_at,
        is_terminal=status in TERMINAL_TASK_RUN_STATUSES,
        task_origin_product="cloud_agents",
        pr_url=(output or {}).get("pr_url"),
    )


def billing_dto(**overrides: Any) -> TaskRunBillingDTO:
    values: dict[str, Any] = {
        "compute_cost_cents": None,
        "inference_cost_cents": None,
        "vcpu_seconds": Decimal(0),
        "gib_seconds": Decimal(0),
        "billable": True,
        "inference_billing": "posthog",
        "rate_card_version": "2026-10-01",
        "waived": False,
        "settled": False,
        "sessions": (),
    }
    return TaskRunBillingDTO(**{**values, **overrides})


class TasksFacadeFake:
    """Stands in for the Tasks product at its facade. It holds the runs that the tests create and change."""

    def __init__(self, team_id: int) -> None:
        self.team_id = team_id
        self.runs: dict[UUID, TaskRunDTO] = {}
        self.create_calls: list[dict[str, Any]] = []
        self.resume_calls: list[dict[str, Any]] = []
        self.billing = billing_dto()
        self.billing_by_task: dict[UUID, TaskRunBillingDTO] = {}
        self.state_reads: list[list[UUID]] = []
        self.billing_reads: list[list[UUID]] = []

    def create(self, **kwargs: Any) -> CloudAgentTaskDTO:
        self.create_calls.append(kwargs)
        run = task_run_dto(team_id=kwargs["team_id"])
        self.runs[run.id] = run
        return CloudAgentTaskDTO(task_id=run.task_id, team_id=run.team_id, run=run, created=True)

    def resume(self, **kwargs: Any) -> TaskRunDTO:
        self.resume_calls.append(kwargs)
        run = task_run_dto(team_id=kwargs["team_id"], task_id=kwargs["task_id"])
        self.runs[run.id] = run
        return run

    def get(self, *, team_id: int, run_id: UUID) -> TaskRunDTO | None:
        run = self.runs.get(run_id)
        return run if run is not None and run.team_id == team_id else None

    def count_active(self, *, team_id: int) -> int:
        return sum(1 for run in self.runs.values() if run.team_id == team_id and not run.is_terminal)

    def task_runs(self, team_id: int, task_id: UUID | None) -> list[TaskRunDTO]:
        """The runs of the task, oldest first."""
        return [run for run in self.runs.values() if run.task_id == task_id and run.team_id == team_id]

    def list_run_ids(self, *, team_id: int, task_id: UUID) -> list[UUID]:
        return [run.id for run in self.task_runs(team_id, task_id)]

    def current_run_id(self, run: CloudAgentRun) -> UUID:
        return self.task_runs(run.team_id, run.task_id)[-1].id

    def set_status(self, run_id: UUID | None, status: str, **changes: Any) -> TaskRunDTO:
        assert run_id is not None
        run = self.runs[run_id]
        output = changes.get("output", run.output)
        self.runs[run_id] = dataclasses.replace(
            run,
            status=status,
            is_terminal=status in TERMINAL_TASK_RUN_STATUSES,
            pr_url=(output or {}).get("pr_url"),
            **changes,
        )
        return self.runs[run_id]

    def _state(self, team_id: int, task_id: UUID) -> CloudAgentTaskStateDTO:
        runs = self.task_runs(team_id, task_id)
        sessions = tuple(
            CloudAgentSessionDTO(
                index=index,
                task_run_id=run.id,
                status=run.status,
                started_at=None if run.status in WAITING_TASK_RUN_STATUSES else run.created_at,
                ended_at=(run.completed_at or run.updated_at) if run.is_terminal else None,
            )
            for index, run in enumerate(runs, start=1)
        )
        latest = runs[-1] if runs else None
        pr_urls = tuple(dict.fromkeys(run.pr_url for run in runs if run.pr_url))
        cancel_source = latest.state.get("cancel_source") if latest is not None else None
        pr_states = {run.pr_url: (run.output or {}).get("pr_state") for run in runs if run.pr_url}
        outputs = [
            {key: value for key, value in (run.output or {}).items() if key not in PULL_REQUEST_OUTPUT_KEYS}
            for run in reversed(runs)
        ]
        return CloudAgentTaskStateDTO(
            task_id=task_id,
            status=latest.status if latest is not None else "queued",
            run_end=classify_task_run_end(latest) if latest is not None and latest.is_terminal else None,
            cancel_source=cancel_source,
            compute_waived=bool(latest is not None and latest.state.get("compute_waived_reason")),
            current_task_run_id=latest.id if latest is not None else None,
            started_at=next((session.started_at for session in sessions if session.started_at), None),
            completed_at=sessions[-1].ended_at if sessions else None,
            updated_at=latest.updated_at if latest is not None else None,
            pr_url=pr_urls[-1] if pr_urls else None,
            pr_urls=pr_urls,
            pull_requests=tuple(CloudAgentPullRequestDTO(url=url, state=pr_states[url]) for url in pr_urls),
            structured_output=next((output for output in outputs if output), None),
            summary=next((run.state["task_summary"] for run in reversed(runs) if run.state.get("task_summary")), None),
            sessions=sessions,
        )

    def get_states(self, *, team_id: int, task_ids: Any) -> dict[UUID, CloudAgentTaskStateDTO]:
        self.state_reads.append(list(task_ids))
        return {task_id: self._state(team_id, task_id) for task_id in task_ids}

    def get_billing(self, *, team_id: int, task_ids: Any) -> dict[UUID, TaskRunBillingDTO]:
        self.billing_reads.append(list(task_ids))
        return {task_id: self.billing_by_task.get(task_id, self.billing) for task_id in task_ids}

    def list_task_ids(self, *, team_id: int, statuses: Any, limit: int, **time_range: Any) -> list[UUID]:
        task_ids = dict.fromkeys(run.task_id for run in self.runs.values() if run.team_id == team_id)
        return [task_id for task_id in task_ids if self._state(team_id, task_id).status in statuses][:limit]

    def summarize_usage(
        self, *, team_id: int, date_from: datetime, date_to: datetime, limit: int
    ) -> CloudAgentUsageDTO:
        first_runs = {run.task_id: run for run in reversed(self.runs.values()) if run.team_id == team_id}
        rows = [
            CloudAgentTaskUsageDTO(
                task_id=task_id,
                created_at=run.created_at,
                compute_cost_cents=billing.compute_cost_cents,
                inference_cost_cents=billing.inference_cost_cents,
                vcpu_seconds=billing.vcpu_seconds,
                gib_seconds=billing.gib_seconds,
                inference_billing=billing.inference_billing,
            )
            for task_id, run in first_runs.items()
            if run.created_at is not None and date_from <= run.created_at < date_to
            for billing in [self.billing_by_task.get(task_id, self.billing)]
        ]
        return CloudAgentUsageDTO(rows=tuple(rows[:limit]), truncated=len(rows) > limit)


class TasksFakeMixin:
    """Patches every Tasks facade function that the run logic calls, and the Redis bucket of the create rate."""

    tasks: TasksFacadeFake
    mocks: dict[str, MagicMock]

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        self.tasks = TasksFacadeFake(self.team.id)  # type: ignore[attr-defined]
        allowed = BucketDecision(allowed=True, remaining=9, limit=10, retry_after=0, reset=0)
        inference = InferenceDecision(
            mode="posthog",
            adapter="claude",
            credential_kind=None,
            owner_user_id=None,
            run_state_updates={},
            resolved_from_auto=True,
        )
        targets: dict[str, Any] = {
            f"{LOGIC}.runs.create_cloud_agent_task": {"side_effect": self.tasks.create},
            f"{LOGIC}.runs.resume_cloud_agent_task": {"side_effect": self.tasks.resume},
            f"{LOGIC}.runs.get_cloud_agent_task_run": {"side_effect": self.tasks.get},
            f"{LOGIC}.streams.get_cloud_agent_task_run": {"side_effect": self.tasks.get},
            f"{LOGIC}.runs.count_active_cloud_agent_runs": {"side_effect": self.tasks.count_active},
            f"{LOGIC}.runs.list_cloud_agent_task_run_ids": {"side_effect": self.tasks.list_run_ids},
            f"{LOGIC}.runs.list_cloud_agent_task_ids": {"side_effect": self.tasks.list_task_ids},
            f"{LOGIC}.run_rows.get_cloud_agent_task_states": {"side_effect": self.tasks.get_states},
            f"{LOGIC}.run_rows.get_cloud_agent_tasks_billing": {"side_effect": self.tasks.get_billing},
            f"{LOGIC}.usage.summarize_cloud_agent_usage": {"side_effect": self.tasks.summarize_usage},
            f"{LOGIC}.runs.resolve_inference": {"return_value": inference},
            f"{LOGIC}.runs.cloud_agents_quota_denial": {"return_value": None},
            f"{LOGIC}.runs.cloud_agents_quota_reset_at": {"return_value": None},
            f"{LOGIC}.runs.signal_task_run_user_message": {"return_value": True},
            f"{LOGIC}.runs.cancel_task_run": {"return_value": ("accepted", None)},
            f"{LOGIC}.runs.read_task_run_history": {"return_value": []},
            f"{LOGIC}.limits.consume": {"return_value": allowed},
            f"{LOGIC}.limits.refund": {},
            f"{LOGIC}.analytics.report_user_action": {},
        }
        self.mocks = {}
        for target, config in targets.items():
            patcher = patch(target, **config)
            self.mocks[target.removeprefix(f"{LOGIC}.")] = patcher.start()
            self.addCleanup(patcher.stop)  # type: ignore[attr-defined]

    def make_run(
        self,
        *,
        team: Any = None,
        task_status: str = "queued",
        billing: TaskRunBillingDTO | None = None,
        **overrides: Any,
    ) -> CloudAgentRun:
        """A stored run, and its task with one run in the fake. `billing` is what Tasks reports for the task."""
        team = team or self.team  # type: ignore[attr-defined]
        task_run = task_run_dto(team_id=team.id, status=task_status)
        self.tasks.runs[task_run.id] = task_run
        if billing is not None:
            self.tasks.billing_by_task[task_run.task_id] = billing
        values: dict[str, Any] = {
            "team": team,
            "created_by": self.user,  # type: ignore[attr-defined]
            "prompt": "Fix the flaky test",
            "repository": "acme/app",
            "config": RUN_CONFIG,
            "task_id": task_run.task_id,
        }
        return CloudAgentRun.all_teams.create(**{**values, **overrides})
