"""Ask Temporal whether the workflow of an import job exists and is still executing."""

from __future__ import annotations

from typing import Literal

from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import async_connect

WorkflowState = Literal["running", "closed", "missing", "unknown"]


async def workflow_state(workflow_id: str) -> WorkflowState:
    # A namespace that does not resolve answers NOT_FOUND for every workflow, so only a not-found
    # that names no namespace proves the workflow is missing.
    try:
        client = await async_connect()
        description = await client.get_workflow_handle(workflow_id).describe()
    except RPCError as error:
        if error.status == RPCStatusCode.NOT_FOUND and "namespace" not in error.message.lower():
            return "missing"
        return "unknown"
    except Exception:
        return "unknown"
    return "running" if description.status == WorkflowExecutionStatus.RUNNING else "closed"


async def workflow_exists(workflow_id: str) -> bool:
    """Whether Temporal has the workflow, reading anything but a clean not-found as yes.

    Releasing a live job lets a second import start against it, which is worse than leaving a dead
    job blocked a while longer.
    """
    return await workflow_state(workflow_id) != "missing"


async def workflow_is_running(workflow_id: str) -> bool:
    """Whether the workflow is still executing, reading an unclear answer as yes.

    Only a workflow that Temporal reports as closed or missing counts as stopped, for the same
    reason as above.
    """
    return await workflow_state(workflow_id) in ("running", "unknown")
