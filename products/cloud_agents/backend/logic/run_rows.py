"""Read `CloudAgentRun` rows and turn them into the public shape of a run.

A row holds what this product owns. The status, the result, the agent sessions and the cost of
a run come from Tasks at each read, in two calls for any number of rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from django.db.models import QuerySet

from posthog.dataclasses import frozen

from products.tasks.backend.facade.cloud_agents import get_cloud_agent_task_states, get_cloud_agent_tasks_billing
from products.tasks.backend.facade.contracts import CloudAgentTaskStateDTO, TaskRunBillingDTO
from products.tasks.backend.facade.pricing import cloud_agents_hourly_price_usd

from ..facade.contracts import AgentSessionDTO, ResolvedRunConfig, RunDTO, RunNotFound, RunResultDTO, SizeSpec
from ..facade.enums import CallerKind, CloudAgentRunStatus, SizeName, size_shape
from ..models import CloudAgentRun
from . import status as status_logic
from .cost import to_cost_dto


@frozen
class TasksData:
    """What Tasks holds for a set of runs, by task id."""

    states: dict[UUID, CloudAgentTaskStateDTO]
    billing: dict[UUID, TaskRunBillingDTO]


def run_rows(team_id: int) -> QuerySet[CloudAgentRun]:
    return CloudAgentRun.objects.for_team(team_id).select_related("created_by", "preset")


def get_run_row(team_id: int, run_id: UUID) -> CloudAgentRun:
    run = run_rows(team_id).filter(id=run_id).first()
    if run is None:
        raise RunNotFound()
    return run


def size_spec(size: SizeName) -> SizeSpec:
    shape = size_shape(size)
    return SizeSpec.from_name(size, price_per_hour_usd=cloud_agents_hourly_price_usd(shape.vcpu, shape.memory_gib))


def read_task_state(team_id: int, run: CloudAgentRun) -> CloudAgentTaskStateDTO | None:
    """The state of the task of the run. None for a run that has no task yet."""
    if run.task_id is None:
        return None
    return get_cloud_agent_task_states(team_id=team_id, task_ids=[run.task_id])[run.task_id]


def read_task_billing(team_id: int, run: CloudAgentRun) -> TaskRunBillingDTO | None:
    """The charges of the task of the run. None for a run that has no task yet."""
    if run.task_id is None:
        return None
    return get_cloud_agent_tasks_billing(team_id=team_id, task_ids=[run.task_id])[run.task_id]


def read_tasks_data(team_id: int, runs: Sequence[CloudAgentRun]) -> TasksData:
    task_ids = [run.task_id for run in runs if run.task_id is not None]
    if not task_ids:
        return TasksData(states={}, billing={})
    return TasksData(
        states=get_cloud_agent_task_states(team_id=team_id, task_ids=task_ids),
        billing=get_cloud_agent_tasks_billing(team_id=team_id, task_ids=task_ids),
    )


def _to_session_dtos(state: CloudAgentTaskStateDTO | None) -> list[AgentSessionDTO]:
    if state is None:
        return []
    return [
        AgentSessionDTO(
            index=session.index,
            task_run_id=session.task_run_id,
            status=status_logic.session_status_for(session.status),
            started_at=session.started_at,
            ended_at=session.ended_at,
        )
        for session in state.sessions
    ]


def run_status(state: CloudAgentTaskStateDTO | None) -> status_logic.RunStatus:
    """The public status of a run whose task has `state`."""
    if state is None:
        # A run with no task yet is a create that is not committed, so it reads as queued.
        return status_logic.run_status_for("queued")
    return status_logic.run_status_for(
        state.status,
        run_end=state.run_end,
        cancel_source=state.cancel_source,
        compute_waived=state.compute_waived,
        pull_request_states=[pull_request.state for pull_request in state.pull_requests],
    )


def task_ids_with_status(team_id: int, status: CloudAgentRunStatus, task_ids: Sequence[UUID]) -> list[UUID]:
    """The tasks in `task_ids` whose run has `status` now. One read of the states of all the tasks."""
    if not task_ids:
        return []
    states = get_cloud_agent_task_states(team_id=team_id, task_ids=task_ids)
    return [task_id for task_id in task_ids if run_status(states[task_id]).status == status]


def build_run_dto(
    run: CloudAgentRun, state: CloudAgentTaskStateDTO | None, billing: TaskRunBillingDTO | None
) -> RunDTO:
    config = ResolvedRunConfig.from_json(run.config)
    # A soft-deleted preset keeps its row, so the run still names the preset it used.
    preset = run.preset
    created_by = run.created_by
    status = run_status(state)
    updated_at = run.updated_at
    if state is not None and state.updated_at is not None:
        updated_at = max(updated_at, state.updated_at)
    return RunDTO(
        id=run.id,
        status=status.status,
        status_reason=status.reason,
        status_detail=status_logic.status_detail_for(status.reason),
        created_at=run.created_at,
        updated_at=updated_at,
        started_at=state.started_at if state is not None else None,
        ended_at=state.completed_at if state is not None else None,
        prompt=run.prompt,
        repositories=config.repositories,
        preset_id=preset.id if preset is not None else None,
        preset_name=preset.name if preset is not None else None,
        config=config,
        size=size_spec(config.size),
        result=RunResultDTO(
            pr_url=state.pr_url if state is not None else None,
            pr_urls=list(state.pr_urls) if state is not None else [],
            summary=state.summary if state is not None else None,
            # Without a schema, the other fields of the Tasks output are not a result of this API.
            output=state.structured_output if state is not None and config.output_schema is not None else None,
        ),
        cost=to_cost_dto(billable=run.billable, inference=run.config.get("inference"), billing=billing),
        agent_sessions=_to_session_dtos(state),
        tags=list(run.tags or []),
        metadata=dict(run.metadata or {}),
        created_by_id=created_by.id if created_by is not None else None,
        created_by_email=created_by.email if created_by is not None else None,
        caller_kind=CallerKind(run.caller_kind),
    )


def to_run_dtos(team_id: int, runs: Sequence[CloudAgentRun]) -> list[RunDTO]:
    """The public shape of each run. Tasks is read two times for the whole sequence, not for each run."""
    tasks = read_tasks_data(team_id, runs)
    return [
        build_run_dto(
            run,
            tasks.states.get(run.task_id) if run.task_id is not None else None,
            tasks.billing.get(run.task_id) if run.task_id is not None else None,
        )
        for run in runs
    ]


def to_run_dto(team_id: int, run: CloudAgentRun) -> RunDTO:
    return to_run_dtos(team_id, [run])[0]
