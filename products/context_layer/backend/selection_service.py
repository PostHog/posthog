import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import asdict
from datetime import timedelta
from threading import BoundedSemaphore

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.ph_client import get_feature_flag_or_none

from products.context_layer.backend.models import ContextSelectionAssignment, ContextSelectionAttempt
from products.context_layer.backend.selection_model import GATE, RELEVANCE, SelectionJudge, request_descriptor
from products.context_layer.backend.selection_search import render, retrieve
from products.context_layer.backend.selection_sources import (
    load_projection,
    search_business_knowledge,
    validate_candidates,
)
from products.context_layer.backend.selection_types import (
    CONFIG_VERSION,
    GATE_THRESHOLD,
    MAX_CONTEXT_CHARS,
    MAX_ITEMS,
    RELEVANCE_THRESHOLD,
    SOURCE_LIMITS,
    Candidate,
    PreparedContext,
    SelectionInput,
    digest,
)
from products.tasks.backend.models import Task, TaskRun

# No unbounded executor queue: a busy process skips selection instead of accumulating work.
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
        or not (
            run.task.runtime == Task.Runtime.PI
            or (
                run.task.runtime == Task.Runtime.ACP
                and (run.state or {}).get("runtime_adapter", "claude") in ("claude", "codex")
            )
        )
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


def prepare(run: TaskRun, actor: User, selection: SelectionInput, scopes: set[str]) -> PreparedContext:
    started = time.monotonic()
    mode = selection_mode(run, actor)
    if mode == "disabled":
        return PreparedContext()
    check_deadline(started + settings.CONTEXT_SELECTION_TIMEOUT_SECONDS)
    fingerprint = digest(asdict(selection))
    with transaction.atomic():
        assignment, _ = ContextSelectionAssignment.objects.get_or_create(
            task_id=run.task_id,
            defaults={"team_id": run.team_id, "mode": mode},
        )
        mode = assignment.mode
        attempt, created = ContextSelectionAttempt.objects.get_or_create(
            run=run,
            message_id=selection.message_id,
            defaults={
                "team_id": run.team_id,
                "actor": actor,
                "input_hash": fingerprint,
                "mode": mode,
                "expires_at": timezone.now() + timedelta(days=90),
            },
        )
    if not created:
        # Never replay prepared context across actor changes, source revocations, or changed input.
        # A retry proceeds without context, and its receipt records that actual exposure.
        return PreparedContext(selection_id=str(attempt.id), mode=mode, reason="duplicate")
    evidence = {
        "schema_version": 2,
        "request_format": {
            "state_fields": ["user_request", "history", "candidate"],
            "answer_key": "useful",
            "questions": {"gate": GATE.to_json(), "relevance": RELEVANCE.to_json()},
        },
        "config_version": CONFIG_VERSION,
        "configuration": {
            "gate_threshold": GATE_THRESHOLD,
            "relevance_threshold": RELEVANCE_THRESHOLD,
            "max_context_chars": MAX_CONTEXT_CHARS,
            "max_items": MAX_ITEMS,
            "source_limits": SOURCE_LIMITS,
            "timeout_seconds": settings.CONTEXT_SELECTION_TIMEOUT_SECONDS,
        },
        "input": asdict(selection),
        "task_id": str(run.task_id),
        "run_id": str(run.id),
        "actor_id": actor.id,
        "origin": run.task.origin_product,
        "model": settings.HOGQL_PROMPT_JEV_MODEL,
        "provider": "gateway",
        "input_hash": fingerprint,
        "history_completeness": "bounded_runtime_history",
        "calls": [],
        "omitted_sources": {},
        "knowledge_search": {
            "method": "search_knowledge_for_team",
            "limit": 8,
            "corpus_revision": None,
            "historical_replay": False,
        },
        "runtime": "pi" if run.task.runtime == Task.Runtime.PI else (run.state or {}).get("runtime_adapter", "claude"),
        "agent_configuration": {key: (run.state or {}).get(key) for key in ("model", "systemPrompt", "store_skills")},
        "baseline_reference": {"run_id": str(run.id), "storage": "task_run_logs", "default_retention_days": 30},
    }
    attempt.evidence = evidence
    attempt.save(update_fields=["evidence"])
    try:
        if not selection.prompt.strip():
            attempt.status = "no_text"
        elif mode == "control":
            attempt.status = "control"
        else:
            _select(attempt, run, actor, selection, scopes, started)
    except Exception as error:
        attempt.context = ""
        attempt.status = "error"
        evidence["error_type"] = type(error).__name__
    evidence["elapsed_seconds"] = time.monotonic() - started
    attempt.save(update_fields=["evidence", "context", "status"])
    # A failed evidence write must fail the request before a prompt can receive context.
    return PreparedContext(
        selection_id=str(attempt.id),
        mode=mode,
        reason=attempt.status,
        context=attempt.context if mode == "treatment" else "",
    )


def check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("selector_deadline")


def _select(
    attempt: ContextSelectionAttempt,
    run: TaskRun,
    actor: User,
    selection: SelectionInput,
    scopes: set[str],
    started: float,
) -> None:
    evidence = attempt.evidence
    deadline = started + settings.CONTEXT_SELECTION_TIMEOUT_SECONDS
    check_deadline(deadline)
    phase_started = time.monotonic()
    projection = load_projection(run.team_id)
    evidence["timings"] = {"projection_seconds": time.monotonic() - phase_started}
    check_deadline(deadline)
    if projection is None:
        attempt.status = "cache_miss"
        return
    evidence["projection"] = {
        key: projection[key] for key in ("version", "created_at", "capped_sources", "archive_id", "refresh_seconds")
    }
    judge = SelectionJudge(str(attempt.id), str(actor.distinct_id), deadline)
    evidence["planned_requests"] = [request_descriptor(selection.prompt, selection.history)]
    attempt.save(update_fields=["evidence"])
    gate = judge.judge(selection.prompt, selection.history)
    evidence["calls"].append(gate.evidence)
    if gate.probability is None:
        attempt.status = "gate_error"
        return
    if gate.probability <= GATE_THRESHOLD:
        attempt.status = "gate_skipped"
        return
    records = [Candidate(**{**record, "tables": tuple(record.get("tables", []))}) for record in projection["records"]]
    allowed_kinds = set()
    if "llm_skill:read" in scopes:
        allowed_kinds.add("skill")
    if "data_catalog:read" in scopes:
        allowed_kinds.update(("metric", "certification", "relationship"))
    phase_started = time.monotonic()
    shortlisted = retrieve(selection.prompt + "\n" + selection.history, [r for r in records if r.kind in allowed_kinds])
    evidence["timings"]["retrieval_seconds"] = time.monotonic() - phase_started
    phase_started = time.monotonic()
    check_deadline(deadline)
    candidates = validate_candidates(run.team, actor, shortlisted)
    check_deadline(deadline)
    evidence["timings"]["validation_seconds"] = time.monotonic() - phase_started
    evidence["retrieval"] = {
        "algorithm": "weighted_tokens_v1",
        "shortlist_ids": [c.id for c in shortlisted],
        "candidates": [c.as_json() for c in candidates],
        "filtered_ids": [c.id for c in shortlisted if c.id not in {v.id for v in candidates}],
    }
    phase_started = time.monotonic()
    if "business_knowledge:read" in scopes and _SEARCH_CAPACITY.acquire(blocking=False):
        search = _SEARCH_EXECUTOR.submit(_search, run.team, actor, selection.prompt)
        search.add_done_callback(lambda _: _SEARCH_CAPACITY.release())
        try:
            knowledge = search.result(timeout=max(0, deadline - time.monotonic()))
            candidates.extend(knowledge)
            evidence["retrieval"]["candidates"].extend(c.as_json() for c in knowledge)
        except Exception as error:
            evidence["omitted_sources"]["business_knowledge"] = type(error).__name__
            search.cancel()
    else:
        evidence["omitted_sources"]["business_knowledge"] = "scope_or_capacity"
    evidence["timings"]["knowledge_seconds"] = time.monotonic() - phase_started
    evidence["planned_requests"].extend(request_descriptor(selection.prompt, selection.history, c) for c in candidates)
    attempt.save(update_fields=["evidence"])
    pending = {}
    for candidate in candidates:
        if not _CAPACITY.acquire(blocking=False):
            evidence.setdefault("capacity_skipped_ids", []).append(candidate.id)
            continue
        future = _EXECUTOR.submit(judge.judge, selection.prompt, selection.history, candidate)
        future.add_done_callback(lambda _: _CAPACITY.release())
        pending[future] = candidate
    done, unfinished = wait(pending, timeout=max(0, deadline - time.monotonic()))
    scored = []
    for future in done:
        candidate = pending[future]
        try:
            judgment = future.result()
            evidence["calls"].append(judgment.evidence)
            if judgment.probability is not None:
                scored.append((candidate, judgment.probability))
        except Exception as error:
            evidence["calls"].append({"candidate_id": candidate.id, "error_type": type(error).__name__})
    evidence["timed_out_ids"] = [pending[future].id for future in unfinished]
    for future in unfinished:
        future.cancel()
    check_deadline(deadline)
    # Recheck current rows after external scoring. A changed definition requires a new judgment.
    current = {c.id: c for c in validate_candidates(run.team, actor, [c for c, _ in scored])}
    check_deadline(deadline)
    scored = [(c, score) for c, score in scored if current.get(c.id) == c]
    rendered = render(scored)
    attempt.context = rendered.context
    evidence["decisions"] = rendered.decisions
    evidence["selected_ids"] = rendered.selected_ids
    evidence["rendered_context"] = attempt.context
    evidence["rendered_context_hash"] = digest(attempt.context)
    attempt.status = "selected" if rendered.selected_ids else "empty"
