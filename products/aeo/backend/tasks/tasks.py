"""Scheduled entrypoints for the AEO citation runner.

The dispatcher is double-gated: a team must be in the AEO_CITATION_TEAM_IDS env
allowlist AND have the `aeo-citation-tracking` feature flag enabled. Both are
empty/off by default, so this is a no-op everywhere until deliberately turned
on. Each eligible team gets its own long-running task so one slow team can't
block another and a worker restart only loses one team's in-flight run.

A run takes hours and a worker rollout kills it part way, so beat dispatches
several times a day and the runner skips the prompts a killed run already
covered. A per-team lease stops two dispatches from running at once.
"""

from __future__ import annotations

import threading

from django.conf import settings
from django.db import InterfaceError, OperationalError

import structlog
from celery import Task, shared_task
from redis.exceptions import LockError, LockNotOwnedError
from redis.lock import Lock

from posthog.celery_queues import CeleryQueue
from posthog.models.team import Team
from posthog.ph_client import feature_enabled_or_false
from posthog.redis import get_client
from posthog.scoping_audit import skip_team_scope_audit

from products.aeo.backend import auto_setup, keyword_suggestions, suggestions
from products.aeo.backend.catalog import recompute_own_citations, sync_brands_from_run
from products.aeo.backend.facade.contracts import (
    AEO_CITATION_TRACKING_FLAG,
    KeywordSuggestionRequest,
    PromptSuggestionRequest,
    SetupRequest,
)
from products.aeo.backend.runner import run_citation_checks

logger = structlog.get_logger(__name__)


# A full run covers the whole prompt set: each prompt makes one web-search call per
# engine (about a minute each), AEO_RUN_CONCURRENCY prompts at a time. Ten hours
# leaves headroom for a slow day and still ends a hung run well before the next
# daily dispatch.
RUN_SOFT_TIME_LIMIT_SECONDS = 10 * 60 * 60
RUN_TIME_LIMIT_SECONDS = RUN_SOFT_TIME_LIMIT_SECONDS + 300
SUGGESTION_SOFT_TIME_LIMIT_SECONDS = 6 * 60
SUGGESTION_TIME_LIMIT_SECONDS = SUGGESTION_SOFT_TIME_LIMIT_SECONDS + 60

# The per-team lease is short and renewed by a side thread while the run is alive, instead of
# lasting the whole time limit. A worker that outlives its termination grace period is SIGKILLed,
# which skips every `finally`, so a lease as long as the time limit would block the catch-up
# dispatches for the rest of the day. Renewal does not depend on prompts completing, so a run
# stalled on slow engine retries keeps its lease.
RUN_LEASE_SECONDS = 10 * 60
RUN_LEASE_RENEW_SECONDS = 60

# One recompute per team at a time. The lock outlives the time limit, so a killed task cannot leave
# two passes writing the same checks.
RECOMPUTE_SOFT_TIME_LIMIT_SECONDS = 20 * 60
RECOMPUTE_TIME_LIMIT_SECONDS = RECOMPUTE_SOFT_TIME_LIMIT_SECONDS + 60
RECOMPUTE_LOCK_SECONDS = RECOMPUTE_TIME_LIMIT_SECONDS + 60
RECOMPUTE_RETRY_SECONDS = 60


def citation_tracking_enabled(team: Team) -> bool:
    """The double gate: a team runs only when it is in the env allowlist AND has
    the flag on. Both default off, so this is fail-closed. Shared by the dispatcher
    and the per-team task so a task queued directly cannot skip the gate."""
    allowlist = {str(raw).strip() for raw in settings.AEO_CITATION_TEAM_IDS}
    if str(team.id) not in allowlist:
        return False
    # No person is behind this scheduled run; the team UUID keeps the flag call
    # well-formed and the organization group lets the flag target teams.
    return feature_enabled_or_false(
        AEO_CITATION_TRACKING_FLAG,
        str(team.uuid),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
    )


@shared_task(ignore_result=True)
@skip_team_scope_audit  # Team is the tenant, not tenant data; the per-team gate scopes what follows
def run_aeo_citation_checks_task() -> None:
    """Beat entrypoint: fan out one runner task per allowlisted, flag-enabled team."""
    for raw_team_id in settings.AEO_CITATION_TEAM_IDS:
        try:
            team = Team.objects.get(id=int(raw_team_id))
        except (Team.DoesNotExist, ValueError):
            logger.warning("aeo_citation_task_unknown_team", team_id=raw_team_id)
            continue
        if not citation_tracking_enabled(team):
            logger.info("aeo_citation_task_flag_disabled", team_id=team.id)
            continue
        run_aeo_citation_checks_for_team_task.delay(team.id)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=RUN_SOFT_TIME_LIMIT_SECONDS,
    time_limit=RUN_TIME_LIMIT_SECONDS,
)
@skip_team_scope_audit  # Team is the tenant, not tenant data; prompts are read via AEOPrompt.objects.for_team
def run_aeo_citation_checks_for_team_task(team_id: int) -> None:
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.warning("aeo_citation_task_unknown_team", team_id=team_id)
        return
    # Re-check the gate here too, so this task fails closed even if it is queued
    # outside the dispatcher (which already checks before fan-out).
    if not citation_tracking_enabled(team):
        logger.info("aeo_citation_task_flag_disabled", team_id=team_id)
        return
    # thread_local=False: the renewal thread must see the token the task thread acquired.
    lease = get_client().lock(f"aeo_citation_run:{team_id}", timeout=RUN_LEASE_SECONDS, thread_local=False)
    if not lease.acquire(blocking=False):
        logger.info("aeo_citation_task_already_running", team_id=team_id)
        return
    stop_renewing = threading.Event()
    lease_lost = threading.Event()
    renewer = threading.Thread(target=_renew_lease, args=(lease, stop_renewing, lease_lost, team_id), daemon=True)
    renewer.start()
    try:
        summary, _ = run_citation_checks(team, stop=lease_lost)
        if summary.run_id:
            result = sync_brands_from_run(team.id, summary.run_id)
            logger.info("aeo_brand_sync_done", team_id=team_id, domains=result.domains, created=result.created)
            # Repairs checks recorded against own domains that changed during the run, and any
            # recompute that a failed task or broker left undone. Queued rather than run inline, so it
            # keeps the recompute's time limit and lock.
            try:
                recompute_aeo_own_citations_task.delay(team_id)
            except Exception:
                logger.exception("aeo_own_citations_reconcile_enqueue_failed", team_id=team_id)
    except Exception:
        # The runner already absorbs per-prompt failures, so anything reaching here is
        # unexpected. Re-raise so Celery marks the task failed and alerting sees it.
        logger.exception("aeo_citation_task_failed", team_id=team_id)
        raise
    finally:
        stop_renewing.set()
        renewer.join(timeout=RUN_LEASE_RENEW_SECONDS)
        try:
            lease.release()
        except LockError:
            # The lease expired during a gap longer than its TTL and a later dispatch may own it now.
            logger.warning("aeo_citation_task_lease_expired", team_id=team_id)


def _renew_lease(lease: Lock, stop: threading.Event, lost: threading.Event, team_id: int) -> None:
    """Keeps the lease alive until `stop`; sets `lost` once the lease is gone so the run ends
    instead of overlapping the dispatch that now owns it."""
    while not stop.wait(RUN_LEASE_RENEW_SECONDS):
        try:
            lease.reacquire()
        except LockNotOwnedError:
            logger.warning("aeo_citation_task_lease_lost", team_id=team_id)
            lost.set()
            return
        except Exception as error:
            # A Redis blip must not end renewal; the next tick retries well inside the TTL.
            logger.warning("aeo_citation_task_lease_renew_failed", team_id=team_id, error=str(error)[:300])


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=SUGGESTION_SOFT_TIME_LIMIT_SECONDS,
    time_limit=SUGGESTION_TIME_LIMIT_SECONDS,
)
@skip_team_scope_audit  # Team is the tenant; prompts are read via AEOPrompt.objects.for_team
def suggest_aeo_prompts_task(team_id: int, job_id: str, request: dict) -> None:
    try:
        suggestions.run_job(
            team_id,
            job_id,
            PromptSuggestionRequest(
                domain=request["domain"],
                brand=request["brand"],
                description=request["description"],
                competitors=tuple(request["competitors"]),
                topics=tuple(request["topics"]),
                count=request["count"],
            ),
        )
    except Exception:
        # Without this the client would poll a pending job until it expires.
        suggestions.fail_job(team_id, job_id, "Prompt suggestions failed. Try again in a minute.")
        logger.exception("aeo_prompt_suggestions_task_failed", team_id=team_id)
        raise


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=SUGGESTION_SOFT_TIME_LIMIT_SECONDS,
    time_limit=SUGGESTION_TIME_LIMIT_SECONDS,
)
@skip_team_scope_audit  # Team is the tenant; keywords, prompts and checks are read via for_team
def suggest_aeo_keywords_task(team_id: int, job_id: str, request: dict) -> None:
    try:
        keyword_suggestions.run_job(
            team_id,
            job_id,
            KeywordSuggestionRequest(
                domain=request["domain"],
                brand=request["brand"],
                description=request["description"],
                count=request["count"],
            ),
        )
    except Exception:
        # Without this the client would poll a pending job until it expires.
        keyword_suggestions.fail_job(team_id, job_id, keyword_suggestions.FAILED_ERROR)
        logger.exception("aeo_keyword_suggestions_task_failed", team_id=team_id)
        raise


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=auto_setup.SETUP_TASK_SOFT_TIME_LIMIT_SECONDS,
    time_limit=auto_setup.SETUP_TASK_TIME_LIMIT_SECONDS,
)
@skip_team_scope_audit  # Team is the tenant; brands, prompts, keywords and checks are read via for_team
def set_up_aeo_task(team_id: int, job_id: str, request: dict) -> None:
    try:
        auto_setup.run_job(
            team_id,
            job_id,
            SetupRequest(
                domain=request["domain"],
                brand=request["brand"],
                description=request["description"],
                # A task queued before this field existed carries no key and queues no run.
                run_first_check=request.get("run_first_check", False),
                only_first_run=request.get("only_first_run", False),
            ),
        )
    except Exception:
        # Without this the client would poll a pending job until it expires.
        auto_setup.fail_job(team_id, job_id, auto_setup.FAILED_ERROR)
        logger.exception("aeo_setup_task_failed", team_id=team_id)
        raise


class RecomputeAlreadyRunning(Exception):
    pass


@shared_task(
    bind=True,
    ignore_result=True,
    autoretry_for=(OperationalError, InterfaceError, RecomputeAlreadyRunning),
    retry_backoff=RECOMPUTE_RETRY_SECONDS,
    max_retries=5,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=RECOMPUTE_SOFT_TIME_LIMIT_SECONDS,
    time_limit=RECOMPUTE_TIME_LIMIT_SECONDS,
)
@skip_team_scope_audit  # Team is the tenant; checks are read and written via AEOCitationCheck.objects.for_team
def recompute_aeo_own_citations_task(self: Task, team_id: int) -> None:
    # A recompute that is already running may have read the domains before this change, so wait for it
    # rather than skip. Its passes and this one only touch checks whose key is stale.
    lock = get_client().lock(f"aeo_own_citations_recompute:{team_id}", timeout=RECOMPUTE_LOCK_SECONDS)
    if not lock.acquire(blocking=False):
        raise RecomputeAlreadyRunning()
    try:
        changed = recompute_own_citations(team_id)
        logger.info("aeo_own_citations_recomputed", team_id=team_id, changed=changed)
    finally:
        try:
            lock.release()
        except LockError:
            logger.warning("aeo_own_citations_recompute_lock_expired", team_id=team_id)
