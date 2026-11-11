from typing import Any

from celery import shared_task
from structlog import get_logger

from posthog.celery_queues import CeleryQueue
from posthog.exceptions_capture import capture_exception
from posthog.scoping_audit import skip_team_scope_audit

from products.cdp.backend.services.invocation_replay import (
    ReplayCriteria,
    ReplayPlan,
    claim_replay,
    execute_replay,
    mark_replay_dispatch_unknown,
    mark_replay_failed,
    mark_replay_refused,
    plan_replay,
    start_claimed_send,
)

logger = get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@skip_team_scope_audit
def run_invocation_replay(criteria: dict[str, Any], fingerprint: str, actor: str, claim: str) -> None:
    if not start_claimed_send(fingerprint, claim):
        logger.warning("invocation_replay_claim_superseded", fingerprint=fingerprint)
        return
    # The plan is computed again here because only the criteria cross the queue.
    # Between the review and this task the runs can change, and then the task
    # must send nothing rather than a set nobody reviewed.
    try:
        plan = plan_replay(ReplayCriteria.from_payload(criteria))
    except Exception:
        logger.exception("invocation_replay_planning_failed", fingerprint=fingerprint)
        mark_replay_failed(fingerprint, "The plan could not be computed again, so nothing was sent.")
        raise
    if plan.fingerprint != fingerprint:
        logger.warning("invocation_replay_plan_changed", fingerprint=fingerprint, new_fingerprint=plan.fingerprint)
        mark_replay_refused(fingerprint, "The runs changed between the review and the send, so nothing was sent.")
        return
    execute_replay(plan, actor=actor, claim=claim)


def dispatch_invocation_replay(plan: ReplayPlan, *, actor: str) -> bool:
    """Queue the send. Returns False when this plan was already sent. Raises ReplayOverlapError on an overlap."""
    claim = claim_replay(plan, actor=actor)
    if claim is None:
        return False
    # The send runs in a task, because a plan can need hundreds of requests and a web request would time out.
    try:
        run_invocation_replay.delay(plan.criteria.to_payload(), plan.fingerprint, actor, claim)
    except Exception as error:
        capture_exception(error)
        mark_replay_dispatch_unknown(plan.fingerprint)
    return True
