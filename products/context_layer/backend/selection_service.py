import time
from concurrent.futures import ThreadPoolExecutor, wait
from threading import BoundedSemaphore, Lock
from uuid import uuid4

from django.conf import settings
from django.db import close_old_connections

import structlog

from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.ph_client import get_feature_flag_or_none, ph_background_capture

from products.context_layer.backend.selection_model import SelectionJudge
from products.context_layer.backend.selection_search import render
from products.context_layer.backend.selection_sources import (
    search_business_knowledge,
    search_sources,
    validate_candidates,
)
from products.context_layer.backend.selection_types import (
    CONFIG_VERSION,
    GATE_THRESHOLD,
    Candidate,
    PreparedContext,
    SelectionInput,
)
from products.tasks.backend.models import Task, TaskRun

logger = structlog.get_logger(__name__)

# Busy processes skip optional context rather than accumulate unbounded work.
_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="context-selection")
_CAPACITY = BoundedSemaphore(64)
_SEARCH_CAPACITY = BoundedSemaphore(1)
_SEARCH_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="context-knowledge")


def _search(team: Team, actor: User, prompt: str) -> list[Candidate]:
    close_old_connections()
    try:
        with team_scope(team.id):
            return search_business_knowledge(team, actor, prompt)
    finally:
        close_old_connections()


def selection_mode(run: TaskRun, actor: User) -> str:
    if (
        not actor.is_staff
        or run.team_id not in settings.CONTEXT_SELECTION_ALLOWED_TEAM_IDS
        or run.task.runtime != Task.Runtime.ACP
        or (run.state or {}).get("runtime_adapter", "claude") not in ("claude", "codex")
        or run.environment != TaskRun.Environment.CLOUD
        or run.task.origin_product not in (Task.OriginProduct.POSTHOG_AI, Task.OriginProduct.SLACK)
    ):
        return "disabled"
    value = get_feature_flag_or_none(
        "phai-context-selection",
        str(run.task_id),
        groups={"organization": str(run.team.organization_id), "project": str(run.team_id)},
        group_properties={"organization": {"id": str(run.team.organization_id)}, "project": {"id": str(run.team_id)}},
        person_properties={"is_staff": actor.is_staff},
        send_feature_flag_events=False,
    )
    return str(value) if value in ("shadow", "control", "treatment") else "disabled"


def check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("selector_deadline")


def prepare(run: TaskRun, actor: User, selection: SelectionInput, scopes: set[str]) -> PreparedContext:
    started = time.monotonic()
    selection_id = str(uuid4())
    mode = "disabled"
    context = ""
    reason = "disabled"
    properties = {
        "task_id": str(run.task_id),
        "task_run_id": str(run.id),
        "run_id": str(run.id),
        "message_id": selection.message_id,
    }
    observation: dict[str, object] = {}
    try:
        mode = selection_mode(run, actor)
        if mode == "disabled":
            return PreparedContext()
        deadline = started + settings.CONTEXT_SELECTION_TIMEOUT_SECONDS
        if not selection.prompt.strip():
            reason = "no_text"
        elif mode == "control":
            reason = "control"
        else:
            context, reason = _select(run, actor, selection, scopes, selection_id, deadline, properties, observation)
    except Exception as error:
        context, reason = "", "error"
        observation["error_type"] = type(error).__name__
    try:
        ph_background_capture()(
            distinct_id=str(actor.distinct_id),
            event="$ai_span",
            properties={
                **properties,
                "$ai_trace_id": selection_id,
                "$ai_span_id": selection_id,
                "$ai_span_name": "Context selection",
                "$ai_product": "posthog_ai",
                "$ai_latency": time.monotonic() - started,
                "$ai_input_state": {"prompt": selection.prompt, "history": selection.history},
                "$ai_output_state": {**observation, "context": context, "mode": mode, "reason": reason},
                "ai_stage": "context_selection",
                "selection_id": selection_id,
                "config_version": CONFIG_VERSION,
                "team_id": run.team_id,
                "runtime_version": selection.runtime_version,
                "history_source": selection.history_source,
                "prompt_char_count": selection.prompt_char_count,
            },
        )
    except Exception:
        logger.exception("context_selection_capture_failed", selection_id=selection_id)
    return PreparedContext(
        selection_id=selection_id, mode=mode, reason=reason, context=context if mode == "treatment" else ""
    )


def _select(
    run: TaskRun,
    actor: User,
    selection: SelectionInput,
    scopes: set[str],
    selection_id: str,
    deadline: float,
    properties: dict[str, str],
    observation: dict[str, object],
) -> tuple[str, str]:
    check_deadline(deadline)
    errors: list[dict[str, str]] = []
    error_lock = Lock()

    def report_error(candidate_id: str, error_type: str) -> None:
        with error_lock:
            errors.append({"candidate_id": candidate_id, "error_type": error_type})
            observation["scorer_errors"] = list(errors)

    observation["scorer_errors"] = []
    judge = SelectionJudge(selection_id, str(actor.distinct_id), deadline, properties, report_error)
    gate = judge.judge(selection.prompt, selection.history)
    observation["gate_probability"] = gate
    if gate is None:
        return "", "gate_error"
    if gate <= GATE_THRESHOLD:
        return "", "gate_skipped"
    started = time.monotonic()
    knowledge = None
    if "business_knowledge:read" in scopes and _SEARCH_CAPACITY.acquire(blocking=False):
        try:
            knowledge = _SEARCH_EXECUTOR.submit(_search, run.team, actor, selection.prompt)
        except Exception:
            _SEARCH_CAPACITY.release()
            raise
        knowledge.add_done_callback(lambda _: _SEARCH_CAPACITY.release())
    try:
        candidates = search_sources(run.team, actor, selection.prompt + "\n" + selection.history, scopes)
        if knowledge is not None:
            try:
                # Reserve half the remaining budget for scoring sources that are already ready.
                candidates.extend(knowledge.result(timeout=max(0, (deadline - time.monotonic()) / 2)))
            except Exception as error:
                observation["knowledge_error"] = type(error).__name__
    finally:
        if knowledge is not None:
            knowledge.cancel()
    observation["retrieval_seconds"] = time.monotonic() - started
    observation["candidate_count"] = len(candidates)
    check_deadline(deadline)
    pending = {}
    for candidate in candidates:
        if not _CAPACITY.acquire(blocking=False):
            continue
        try:
            future = _EXECUTOR.submit(judge.judge, selection.prompt, selection.history, candidate)
        except Exception:
            _CAPACITY.release()
            raise
        future.add_done_callback(lambda _: _CAPACITY.release())
        pending[future] = candidate
    done, unfinished = wait(pending, timeout=max(0, deadline - time.monotonic()))
    scored: list[tuple[Candidate, float]] = []
    for future in done:
        probability = future.result()
        if probability is not None:
            scored.append((pending[future], probability))
    observation["unscored_count"] = len(candidates) - len(scored)
    for future in unfinished:
        future.cancel()
    check_deadline(deadline)
    # Definitions and access can change while the external scorer runs.
    current = {(c.kind, c.id): c for c in validate_candidates(run.team, actor, [c for c, _ in scored])}
    scored = [(c, score) for c, score in scored if current.get((c.kind, c.id)) == c]
    check_deadline(deadline)
    rendered = render(scored, selection_id)
    observation["decisions"] = rendered.decisions
    observation["selected_ids"] = rendered.selected_ids
    return rendered.context, "selected" if rendered.selected_ids else "empty"
