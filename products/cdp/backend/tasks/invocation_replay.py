from typing import Any

from celery import shared_task
from structlog import get_logger

from posthog.celery_queues import CeleryQueue
from posthog.scoping_audit import skip_team_scope_audit

from products.cdp.backend.services.invocation_replay import (
    ReplayCriteria,
    execute_replay,
    mark_replay_refused,
    plan_replay,
)

logger = get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@skip_team_scope_audit
def run_invocation_replay(criteria: dict[str, Any], fingerprint: str, actor: str) -> None:
    # The plan is computed again here because only the criteria cross the queue.
    # Between the review and this task the runs can change, and then the task
    # must send nothing rather than a set nobody reviewed.
    plan = plan_replay(ReplayCriteria.from_payload(criteria))
    if plan.fingerprint != fingerprint:
        logger.warning("invocation_replay_plan_changed", fingerprint=fingerprint, new_fingerprint=plan.fingerprint)
        mark_replay_refused(fingerprint, "The runs changed between the review and the send, so nothing was sent.")
        return
    execute_replay(plan, actor=actor)
