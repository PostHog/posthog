import uuid
import asyncio
import threading
from typing import Optional

from django.conf import settings

import structlog
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.temporal.common.client import async_connect

from .workflow import AIVisibilityWorkflowInput

logger = structlog.get_logger(__name__)


async def _start_ai_visibility_workflow(
    workflow_id: str, domain: str, team_id: Optional[int] = None, user_id: Optional[int] = None
) -> str:
    client = await async_connect()

    handle = await client.start_workflow(
        "ai-visibility",
        AIVisibilityWorkflowInput(domain=domain, team_id=team_id, user_id=user_id),
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.AI_VISIBILITY_TASK_QUEUE,
        retry_policy=RetryPolicy(maximum_attempts=3),
    )

    return handle.id


def trigger_ai_visibility_workflow(domain: str, team_id: Optional[int] = None, user_id: Optional[int] = None) -> str:
    """
    Fire-and-forget starter for the AI Visibility workflow. Returns the workflow id immediately.
    """
    workflow_id = f"ai-visibility-{team_id or 'public'}-{uuid.uuid4().hex}"

    def _runner() -> None:
        try:
            asyncio.run(_start_ai_visibility_workflow(workflow_id, domain, team_id, user_id))
            logger.info(
                "ai_visibility.workflow_started",
                domain=domain,
                team_id=team_id,
                user_id=user_id,
                workflow_id=workflow_id,
            )
        except Exception:
            logger.exception("ai_visibility.workflow_start_failed", domain=domain, team_id=team_id, user_id=user_id)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()

    return workflow_id
