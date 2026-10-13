"""Temporal client helper for starting the canvas build workflow.

Modeled on ``products/stamphog/backend/temporal/client.py``: a thin fire-and-forget
bridge from Django (``transaction.on_commit`` in the build service) into Temporal.
"""

import logging
from datetime import timedelta

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import async_connect

from products.canvas.backend.temporal.activities import CanvasBuildInput

logger = logging.getLogger(__name__)

CANVAS_BUILD_WORKFLOW = "canvas-build"

# Bounds the whole workflow so an execution stranded on a queue with no pollers closes
# instead of blocking its build forever: the sweeper's redelivery is a no-op while a
# workflow with the build's id is open (ALLOW_DUPLICATE only permits reuse after close).
# Sized past the activity's worst case (3 attempts x 330s start_to_close plus backoff).
CANVAS_BUILD_WORKFLOW_TIMEOUT = timedelta(minutes=20)


@async_to_sync
async def execute_canvas_build_workflow(team_id: int, build_id: str) -> None:
    """Start the ``canvas-build`` workflow for a queued CanvasBuild.

    Fire-and-forget. The workflow id is the build id, so a duplicate dispatch (the
    sweeper re-delivering a stale queued build whose workflow is in fact alive) is a
    no-op while a workflow with that id runs; a sequential re-dispatch of the same
    build (the retry action) starts fresh under ALLOW_DUPLICATE.
    """
    client = await async_connect()
    try:
        await client.start_workflow(
            CANVAS_BUILD_WORKFLOW,
            CanvasBuildInput(team_id=team_id, build_id=build_id),
            id=f"canvas-build-{build_id}",
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            task_queue=settings.CANVAS_BUILD_TASK_QUEUE,
            execution_timeout=CANVAS_BUILD_WORKFLOW_TIMEOUT,
            # Retries live on the activity; a workflow retry would re-run a build whose
            # row run_canvas_build already moved to a terminal state.
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
    except WorkflowAlreadyStartedError:
        logger.info(
            "canvas_build_workflow_already_running",
            extra={"team_id": team_id, "build_id": build_id},
        )
