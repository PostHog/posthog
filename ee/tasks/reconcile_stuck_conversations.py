from datetime import timedelta

from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync
from celery import shared_task

from posthog.tasks.utils import CeleryQueue
from posthog.temporal.ai.chat_agent import CHAT_AGENT_WORKFLOW_TIMEOUT
from posthog.temporal.ai.research_agent import RESEARCH_AGENT_WORKFLOW_TIMEOUT

from ee.hogai.core.executor import AgentExecutor
from ee.models.assistant import Conversation

logger = structlog.get_logger(__name__)

# Past the longest possible workflow execution timeout, Temporal has already force-terminated the
# workflow, so a conversation still flagged busy is definitively stuck. The buffer absorbs clock
# skew and the gap between termination and the (skipped) status cleanup.
STUCK_CONVERSATION_THRESHOLD_SECONDS = max(CHAT_AGENT_WORKFLOW_TIMEOUT, RESEARCH_AGENT_WORKFLOW_TIMEOUT) + 5 * 60


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
def reconcile_stuck_conversations() -> None:
    """Release stale conversation locks left behind by workers that died mid-generation.

    The runner sets `Conversation.status = IN_PROGRESS` while a generation runs and resets it to
    IDLE in a `finally`. A killed worker or a hard workflow termination skips that `finally`,
    leaving the conversation stuck and rejecting every future message with a 409. This safety net
    resets any long-stuck conversation whose Temporal workflow is no longer running, so a
    conversation recovers even if the user never sends another message to trigger the request-path
    reconciliation in the conversation viewset.
    """
    cutoff = timezone.now() - timedelta(seconds=STUCK_CONVERSATION_THRESHOLD_SECONDS)
    stuck = (
        Conversation.objects.filter(
            status__in=[Conversation.Status.IN_PROGRESS, Conversation.Status.CANCELING],
            updated_at__lt=cutoff,
        )
        .exclude(deleted=True)
        .iterator()
    )

    reset_count = 0
    for conversation in stuck:
        try:
            if async_to_sync(AgentExecutor(conversation).has_running_workflow)():
                continue
            conversation.status = Conversation.Status.IDLE
            conversation.save(update_fields=["status", "updated_at"])
            reset_count += 1
        except Exception as e:
            logger.warning(
                "Failed to reconcile stuck conversation",
                conversation_id=str(conversation.id),
                error=str(e),
            )

    if reset_count:
        logger.info("Reconciled stuck conversations", reset_count=reset_count)
