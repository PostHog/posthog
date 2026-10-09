"""Start, continue, cancel and read cloud agent runs. Each run is one task of the Tasks product."""

from __future__ import annotations

import json
import hashlib
import dataclasses
from collections.abc import Sequence
from datetime import timedelta
from typing import Final, cast, overload
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from posthog.dataclasses import frozen

from products.tasks.backend.facade.api import read_task_run_history, signal_task_run_user_message
from products.tasks.backend.facade.cancellation import cancel_task_run
from products.tasks.backend.facade.cloud_agents import (
    CloudAgentRunNotResumable,
    CloudAgentTaskInvalid,
    CloudAgentTaskNotFound,
    count_active_cloud_agent_runs,
    create_cloud_agent_task,
    get_cloud_agent_task_run,
    list_cloud_agent_task_ids,
    list_cloud_agent_task_run_ids,
    resume_cloud_agent_task,
)
from products.tasks.backend.facade.compute import SandboxSize
from products.tasks.backend.facade.compute_quota import (
    ComputeBillingLimitExceeded,
    cloud_agents_quota_denial,
    cloud_agents_quota_reset_at,
)
from products.tasks.backend.facade.contracts import TaskRunDTO
from products.tasks.backend.facade.inference import (
    InferenceDecision,
    InferenceRequest,
    InferenceUnavailable,
    resolve_inference,
)
from products.tasks.backend.facade.model_catalogue import runtime_adapter_for
from products.tasks.backend.facade.run_config import RuntimeAdapter, get_default_model_for_runtime_adapter

from ..facade.contracts import (
    CallerIdentity,
    CredentialOwnerRequired,
    IdempotencyKeyReused,
    InvalidInput,
    MessageResult,
    OrganizationDeactivated,
    PresetDTO,
    PresetNotFound,
    ResolvedRunConfig,
    RunCancelUnavailable,
    RunCreateInput,
    RunDone,
    RunDTO,
    RunEventsDTO,
    RunListFilters,
    RunNotFound,
    RunNotReady,
    RunNotResumable,
    RunStopping,
    RunUsageDTO,
    TeamSettingsDTO,
    UsageLimited,
)
from ..facade.enums import CloudAgentRunStatus, InferenceMode
from ..models import CloudAgentRun
from . import (
    limits,
    status as status_logic,
)
from .analytics import capture_event
from .config_resolution import render_prompt, resolve_run_config
from .cost import to_cost_dto, to_session_usage_dtos
from .presets import get_preset, get_preset_by_ref
from .run_rows import (
    build_run_dto,
    get_run_row,
    read_task_billing,
    read_task_state,
    run_rows,
    run_status,
    task_ids_with_status,
    to_run_dto,
    to_run_dtos,
)
from .settings import get_team_settings

MAX_RETRY_AFTER_SECONDS: Final = 24 * 60 * 60
TITLE_MAX_LENGTH: Final = 120
EVENT_LOG_MAX_BYTES: Final = 16 * 1024 * 1024
RUN_ID_STATE_KEY: Final = "cloud_agents_run_id"
# A list with a status filter covers the newest tasks that Tasks gives for the status, up to this
# number, because Tasks holds the status and gives this product the tasks to show.
STATUS_FILTER_MAX_RUNS: Final = 1000
# Tasks stores a task a short time after this product stores its run, in the same request. A
# task that belongs to a run from before `created_before` can thus be newer than that time.
TASK_CREATED_AFTER_RUN_MARGIN: Final = timedelta(minutes=1)


class _DuplicateIdempotencyKey(Exception):
    pass


@frozen
class _ModelSelection:
    runtime_adapter: str
    model: str | None


class RunList(Sequence[RunDTO]):
    """The runs that match a filter, newest first. It reads only the page that a caller takes a slice of."""

    def __init__(self, team_id: int, rows: QuerySet[CloudAgentRun]) -> None:
        self._team_id = team_id
        self._rows = rows

    def __len__(self) -> int:
        return self._rows.count()

    @overload
    def __getitem__(self, index: int) -> RunDTO: ...

    @overload
    def __getitem__(self, index: slice) -> list[RunDTO]: ...

    def __getitem__(self, index: int | slice) -> RunDTO | list[RunDTO]:
        if isinstance(index, slice):
            return to_run_dtos(self._team_id, list(self._rows[index]))
        return to_run_dto(self._team_id, self._rows[index])


# --- Start ---


def request_hash(data: RunCreateInput) -> str:
    """The identity of a create request, so a reused idempotency key with a different body is refused."""
    body = dataclasses.asdict(data)
    body.pop("idempotency_key", None)
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def _origin_key(team_id: int, idempotency_key: str) -> str:
    return f"ca:{hashlib.sha256(f'{team_id}:{idempotency_key}'.encode()).hexdigest()[:40]}"


def _find_replay(team_id: int, idempotency_key: str, body_hash: str) -> RunDTO | None:
    run = run_rows(team_id).filter(idempotency_key=idempotency_key).first()
    if run is None:
        return None
    if run.request_hash != body_hash:
        raise IdempotencyKeyReused()
    return to_run_dto(team_id, run)


def _resolve_preset(team_id: int, ref: str | None, settings: TeamSettingsDTO) -> PresetDTO | None:
    if ref:
        try:
            return get_preset_by_ref(team_id, ref)
        except PresetNotFound:
            raise InvalidInput("This preset does not exist in this project.", attr="preset") from None
    if settings.default_preset_id is None:
        return None
    try:
        return get_preset(team_id, settings.default_preset_id)
    except PresetNotFound:
        return None


def _check_quota(team_id: int, *, billable: bool) -> None:
    """Raise when the project must not start or continue a billed run. An unbilled run has no quota."""
    if not billable:
        return
    denial = cloud_agents_quota_denial(team_id=team_id)
    if denial is None:
        return
    if denial == "organization_deactivated":
        raise OrganizationDeactivated()
    raise UsageLimited(retry_after=_quota_retry_after(team_id))


def _quota_retry_after(team_id: int) -> int | None:
    reset_at = cloud_agents_quota_reset_at(team_id=team_id)
    if reset_at is None:
        return None
    seconds = int((reset_at - timezone.now()).total_seconds())
    return min(max(seconds, 1), MAX_RETRY_AFTER_SECONDS)


def _select_model(model: str | None) -> _ModelSelection:
    """The runtime that drives the model. With no model, PostHog selects the default model of the default runtime."""
    if model is None:
        adapter = RuntimeAdapter.CLAUDE.value
        return _ModelSelection(runtime_adapter=adapter, model=get_default_model_for_runtime_adapter(adapter))
    adapter_for_model = runtime_adapter_for(model)
    if adapter_for_model is None:
        raise InvalidInput("This model is not available. Read the catalog for the models you can use.", attr="model")
    return _ModelSelection(runtime_adapter=adapter_for_model, model=model)


def _resolve_inference(
    team_id: int, caller: CallerIdentity, selection: _ModelSelection, requested: InferenceMode
) -> InferenceDecision:
    try:
        return resolve_inference(
            user_id=caller.user_id,
            team_id=team_id,
            runtime_adapter=selection.runtime_adapter,
            requested=cast(InferenceRequest, requested.value),
        )
    except InferenceUnavailable as error:
        raise InvalidInput(error.detail, attr="inference") from error


def _run_state(run: CloudAgentRun) -> dict[str, object]:
    return {RUN_ID_STATE_KEY: str(run.id)}


def _reasoning_effort(config: ResolvedRunConfig) -> str | None:
    return config.reasoning_effort.value if config.reasoning_effort is not None else None


# Tasks names the request field at fault. These are the fields that have the same name in this API.
_TASK_INVALID_ATTRS: Final = frozenset({"model", "output_schema"})


def _create_run(
    team_id: int,
    caller: CallerIdentity,
    user_id: int,
    data: RunCreateInput,
    config: ResolvedRunConfig,
    selection: _ModelSelection,
    decision: InferenceDecision,
    idempotency_key: str | None,
    body_hash: str | None,
) -> CloudAgentRun:
    # One transaction holds the row of this product and the rows of Tasks, and Tasks starts its
    # workflow only after the commit. So a failure at any step leaves no row and no sandbox, and a
    # run never exists on one side only. The concurrency count is exact for the same reason: the
    # lock of the guard is held until the new Tasks run is stored.
    with transaction.atomic():
        limits.concurrency_guard(team_id, lambda: count_active_cloud_agent_runs(team_id=team_id))
        try:
            with transaction.atomic():
                run = CloudAgentRun.objects.for_team(team_id).create(
                    team_id=team_id,
                    created_by_id=user_id,
                    caller_kind=caller.kind.value,
                    caller_product=caller.product,
                    billable=caller.billable,
                    prompt=data.prompt,
                    repository=config.repositories[0].name,
                    preset_id=config.preset_id,
                    tags=config.tags,
                    metadata=dict(data.metadata or {}),
                    idempotency_key=idempotency_key,
                    request_hash=body_hash,
                    config={
                        **config.to_json(),
                        "model": selection.model,
                        "runtime_adapter": selection.runtime_adapter,
                        "inference": decision.mode,
                        "inference_requested": config.inference.value,
                    },
                )
        except IntegrityError:
            if idempotency_key is None:
                raise
            raise _DuplicateIdempotencyKey() from None
        try:
            task = create_cloud_agent_task(
                team_id=team_id,
                user_id=user_id,
                prompt=render_prompt(config, data.prompt),
                title=data.prompt[:TITLE_MAX_LENGTH],
                repository=config.repositories[0].name,
                branch=config.repositories[0].initial_branch,
                create_pr=config.create_pr,
                origin_key=_origin_key(team_id, idempotency_key) if idempotency_key else None,
                billable=caller.billable,
                sandbox_size=SandboxSize(config.size.value),
                model=selection.model,
                runtime_adapter=selection.runtime_adapter,
                reasoning_effort=_reasoning_effort(config),
                inactivity_timeout_seconds=config.idle_minutes * 60,
                extra_run_state=_run_state(run),
                inference_state=decision.run_state_updates,
                output_schema=config.output_schema,
            )
        except CloudAgentTaskInvalid as error:
            raise InvalidInput(error.detail, attr=error.attr if error.attr in _TASK_INVALID_ATTRS else None) from error
        if task.run is None:
            raise RuntimeError(f"Tasks returned no run for cloud agent run {run.id}")
        run.task_id = task.task_id
        run.save(update_fields=["task_id", "updated_at"])
    return run


def start_run(
    team_id: int, caller: CallerIdentity, data: RunCreateInput, idempotency_key: str | None = None
) -> tuple[RunDTO, bool]:
    """Start a run. The flag is True when the idempotency key replayed a run that an earlier request started."""
    idempotency_key = idempotency_key or data.idempotency_key
    body_hash = request_hash(data) if idempotency_key else None
    if idempotency_key and body_hash:
        # Before every gate, so a retry of a request that succeeded always gets its run back.
        replay = _find_replay(team_id, idempotency_key, body_hash)
        if replay is not None:
            return replay, True
    if caller.user_id is None:
        raise InvalidInput("A run needs a user. Use a personal API key or an OAuth token of a user.")

    settings = get_team_settings(team_id)
    preset = _resolve_preset(team_id, data.preset, settings)
    config = resolve_run_config(data, preset, settings)
    selection = _select_model(config.model)

    _check_quota(team_id, billable=caller.billable)
    limits.consume_create_rate(team_id)
    try:
        decision = _resolve_inference(team_id, caller, selection, config.inference)
        run = _create_run(
            team_id, caller, caller.user_id, data, config, selection, decision, idempotency_key, body_hash
        )
    except _DuplicateIdempotencyKey:
        limits.refund_create_rate(team_id)
        # A concurrent request with the same key stored its run first.
        replay = _find_replay(team_id, idempotency_key or "", body_hash or "")
        if replay is None:
            raise
        return replay, True
    except BaseException:
        # Nothing started, so the request does not count against the create rate.
        limits.refund_create_rate(team_id)
        raise

    capture_event(
        "cloud_agents_run_created",
        caller,
        team_id,
        {
            "run_id": str(run.id),
            "billable": caller.billable,
            "size": config.size.value,
            "inference_requested": config.inference.value,
            "inference_resolved": decision.mode,
            "preset_used": config.preset_id is not None,
            "has_output_schema": config.output_schema is not None,
            "has_idempotency_key": idempotency_key is not None,
        },
    )
    return to_run_dto(team_id, get_run_row(team_id, run.id)), False


# --- Read ---


def get_run(team_id: int, run_id: UUID) -> RunDTO:
    return to_run_dto(team_id, get_run_row(team_id, run_id))


def get_run_usage(team_id: int, run_id: UUID) -> RunUsageDTO:
    """The cost of a run and its sandbox sessions, as Tasks reports them now."""
    run = get_run_row(team_id, run_id)
    billing = read_task_billing(team_id, run)
    return RunUsageDTO(
        run_id=run.id,
        cost=to_cost_dto(billable=run.billable, inference=run.config.get("inference"), billing=billing),
        sessions=to_session_usage_dtos(billing) if billing is not None else [],
    )


def list_runs(team_id: int, filters: RunListFilters) -> RunList:
    rows = run_rows(team_id)
    if filters.preset_id is not None:
        rows = rows.filter(preset_id=filters.preset_id)
    if filters.repository:
        rows = rows.filter(repository__icontains=filters.repository)
    if filters.tag:
        rows = rows.filter(tags__contains=[filters.tag])
    if filters.created_after is not None:
        rows = rows.filter(created_at__gte=filters.created_after)
    if filters.created_before is not None:
        rows = rows.filter(created_at__lt=filters.created_before)
    if filters.status is not None:
        task_ids = list_cloud_agent_task_ids(
            team_id=team_id,
            statuses=status_logic.task_run_statuses_for(filters.status),
            limit=STATUS_FILTER_MAX_RUNS,
            # The time filters go to Tasks too, so the limit counts only the runs of the time range.
            created_after=filters.created_after,
            created_before=(
                filters.created_before + TASK_CREATED_AFTER_RUN_MARGIN if filters.created_before is not None else None
            ),
        )
        if status_logic.shares_task_run_statuses(filters.status):
            # Tasks cannot tell `idle` from `done`. The other filters go first, so the states are
            # read only for the runs that can be in the result.
            matching = [
                task_id
                for task_id in rows.filter(task_id__in=task_ids).values_list("task_id", flat=True)
                if task_id is not None
            ]
            task_ids = task_ids_with_status(team_id, filters.status, matching)
        rows = rows.filter(task_id__in=task_ids)
    # The id breaks a tie between two runs of the same instant, so a page boundary never repeats a run.
    return RunList(team_id, rows.order_by("-created_at", "-id"))


def get_run_events(team_id: int, run_id: UUID) -> RunEventsDTO:
    """Every stored event of the run, oldest first, across its agent sessions."""
    run = get_run_row(team_id, run_id)
    if run.task_id is None:
        return RunEventsDTO(events=[], truncated=False)
    task_run_ids = list_cloud_agent_task_run_ids(team_id=team_id, task_id=run.task_id)
    # The history of a session holds the sessions before it. So the newest session gives the full
    # log, and when that is too large, the newest earlier session that fits gives the start of it.
    for position, task_run_id in enumerate(reversed(task_run_ids)):
        events = read_task_run_history(task_run_id, run.task_id, team_id, max_bytes=EVENT_LOG_MAX_BYTES)
        if events is not None:
            return RunEventsDTO(events=events, truncated=position > 0)
    return RunEventsDTO(events=[], truncated=bool(task_run_ids))


# --- Continue ---


def _check_credential_owner(run: CloudAgentRun, caller: CallerIdentity) -> None:
    """A run on a user's own subscription spends that user's plan allowance, so only that user continues it."""
    inference = run.config.get("inference")
    if inference == InferenceMode.OWN_SUBSCRIPTION and (caller.user_id is None or caller.user_id != run.created_by_id):
        raise CredentialOwnerRequired()


def _send_to_live_session(team_id: int, run: CloudAgentRun, task_run: TaskRunDTO, content: str) -> bool:
    """Give the message to the running agent. False when its workflow already ended."""
    try:
        delivered = signal_task_run_user_message(
            task_run.id,
            task_run.task_id,
            team_id,
            content=content,
            artifact_ids=[],
            # The creator, so Tasks sees the owner of the credential that the run uses.
            actor_user_id=run.created_by_id,
        )
    except ComputeBillingLimitExceeded:
        raise UsageLimited(retry_after=_quota_retry_after(team_id)) from None
    except RuntimeError:
        raise RunStopping() from None
    return bool(delivered)


def _resume(team_id: int, run_id: UUID, user_id: int, previous: TaskRunDTO, content: str) -> CloudAgentRun:
    # One transaction, for the same reasons as in `_create_run`: a resume starts a sandbox.
    with transaction.atomic():
        limits.concurrency_guard(team_id, lambda: count_active_cloud_agent_runs(team_id=team_id))
        run = CloudAgentRun.objects.for_team(team_id).select_for_update().get(id=run_id)
        # Read while the row lock is held, so two messages cannot resume the same session.
        state = read_task_state(team_id, run)
        if state is None or state.current_task_run_id != previous.id:
            # Another message resumed the run first. Its session is not ready to take a message yet.
            raise RunNotReady()
        config = ResolvedRunConfig.from_json(run.config)
        try:
            resume_cloud_agent_task(
                team_id=team_id,
                task_id=previous.task_id,
                user_id=user_id,
                previous_run_id=previous.id,
                message=content,
                # The size is fixed for the life of the run.
                sandbox_size=SandboxSize(config.size.value),
                model=config.model,
                # The model, the effort and the idle time are fixed too. The task holds the output
                # schema, so each new session must return a result that matches it.
                reasoning_effort=_reasoning_effort(config),
                inactivity_timeout_seconds=config.idle_minutes * 60,
                extra_run_state=_run_state(run),
                inference_state=None,
            )
        except (CloudAgentRunNotResumable, CloudAgentTaskNotFound):
            raise RunNotResumable() from None
        except CloudAgentTaskInvalid as error:
            raise InvalidInput(error.detail) from error
        run.save(update_fields=["updated_at"])
    return run


def send_message(team_id: int, caller: CallerIdentity, run_id: UUID, content: str) -> MessageResult:
    """Send a follow-up message. A live agent gets it. An idle run starts a new agent session with it."""
    run = get_run_row(team_id, run_id)
    state = read_task_state(team_id, run)
    # Before the quota, so a run that can never continue does not tell the caller to try again later.
    if run_status(state).status == CloudAgentRunStatus.DONE:
        raise RunDone()
    _check_quota(team_id, billable=run.billable)
    _check_credential_owner(run, caller)
    if state is None or state.current_task_run_id is None:
        raise RunNotReady()
    task_run = get_cloud_agent_task_run(team_id=team_id, run_id=state.current_task_run_id)
    if task_run is None:
        raise RunNotFound()

    if not task_run.is_terminal:
        if _send_to_live_session(team_id, run, task_run, content):
            capture_event("cloud_agents_run_followup_sent", caller, team_id, {"run_id": str(run.id), "resumed": False})
            return MessageResult(resumed=False, run=build_run_dto(run, state, read_task_billing(team_id, run)))
        task_run = get_cloud_agent_task_run(team_id=team_id, run_id=task_run.id)
        if task_run is None or not task_run.is_terminal:
            # The workflow ended and the run is not stored as ended yet, so it cannot be resumed now.
            raise RunStopping()

    user_id = run.created_by_id or caller.user_id
    if user_id is None:
        raise InvalidInput("A run needs a user. Use a personal API key or an OAuth token of a user.")
    resumed = _resume(team_id, run.id, user_id, task_run, content)
    capture_event("cloud_agents_run_followup_sent", caller, team_id, {"run_id": str(run.id), "resumed": True})
    return MessageResult(resumed=True, run=to_run_dto(team_id, get_run_row(team_id, resumed.id)))


# --- Cancel ---


def cancel_run(team_id: int, caller: CallerIdentity, run_id: UUID) -> tuple[RunDTO, bool]:
    """Ask the run to stop. The flag is False when the run has no agent at work, so there was nothing to cancel.

    An idle run stays idle: it has no sandbox to stop, and this API has no operation that closes a run.
    """
    run = get_run_row(team_id, run_id)
    state = read_task_state(team_id, run)
    if state is None or state.current_task_run_id is None:
        raise RunNotReady()
    if run_status(state).status in (CloudAgentRunStatus.IDLE, CloudAgentRunStatus.DONE):
        return build_run_dto(run, state, read_task_billing(team_id, run)), False
    # The generic cancel has no origin check, so the run is resolved as a Cloud Agents run first.
    task_run = get_cloud_agent_task_run(team_id=team_id, run_id=state.current_task_run_id)
    if task_run is None:
        raise RunNotFound()
    outcome, _ = cancel_task_run(
        task_run.id,
        task_run.task_id,
        team_id,
        source="cloud_agents_api",
        requested_by_user_id=caller.user_id,
        requested_by_distinct_id=caller.distinct_id,
    )
    capture_event("cloud_agents_run_cancelled", caller, team_id, {"run_id": str(run.id), "outcome": outcome})
    match outcome:
        case "accepted" | "already_terminal":
            return to_run_dto(team_id, run), outcome == "accepted"
        case "not_found":
            raise RunNotFound()
        case _:
            raise RunCancelUnavailable()
