"""Temporal workflow adapter boundary.

Declares the Protocol the rest of the product depends on, a Null stub
for tests and dev, and `TemporalWorkflowAdapter` — the real implementation
that talks to a Temporal cluster.

We only ever:
- Start a build workflow when a Deployment is created (one `start_build`
  call per new row).
- Signal cancellation when the user clicks Cancel on a non-terminal
  deployment (`signal_cancel`).

The workflow itself posts status transitions and events back to our
internal API — we never poll Temporal.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from importlib import import_module
from typing import Protocol

from django.conf import settings

import structlog
from temporalio.client import WorkflowHandle as TemporalWorkflowHandle
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import sync_connect

from ..domain.contracts import BuildInput

# Workflow type name registered by the deployments Temporal worker. The
# worker chart isn't deployed yet; flipping `DEPLOYMENTS_WORKFLOW_ADAPTER`
# to this adapter before that lands means workflows get queued and sit
# unprocessed until the worker comes online.
DEPLOYMENT_BUILD_WORKFLOW = "deployment-build"

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class WorkflowHandle:
    """Reference we persist on the Deployment row so cancel() can target the run."""

    workflow_id: str
    run_id: str


class WorkflowAdapter(Protocol):
    def start_build(self, *, workflow_input: BuildInput) -> WorkflowHandle: ...

    def signal_cancel(self, *, workflow_id: str) -> None: ...


class WorkflowError(Exception):
    """Raised when a Temporal start/signal call fails."""


class NullWorkflowAdapter:
    """Stub used in tests. Returns a deterministic WorkflowHandle so callers
    can persist + assert on temporal_workflow_id / temporal_run_id."""

    def start_build(self, *, workflow_input: BuildInput) -> WorkflowHandle:
        wf_id = f"deployment-{workflow_input.deployment_id}"
        return WorkflowHandle(workflow_id=wf_id, run_id=f"{wf_id}-run-0")

    def signal_cancel(self, *, workflow_id: str) -> None:
        return None


class TemporalWorkflowAdapter:
    """Workflow adapter backed by the real Temporal cluster.

    Inert until both:
    - `DEPLOYMENTS_WORKFLOW_ADAPTER` env var points at this class
      (otherwise `get_workflow_adapter()` returns the Null stub).
    - A deployments Temporal worker is running on `DEPLOYMENTS_TASK_QUEUE`
      and has registered the `deployment-build` workflow type.

    Until the worker lands, flipping the env var still "works" — workflows
    get queued and sit unprocessed. That's a useful intermediate state
    for observability, not a regression.

    `start_build` is called synchronously from the public POST handler,
    so we use `sync_connect` + `asyncio.run` rather than async views.
    Same pattern as `posthog/api/proxy_record.py`.
    """

    def _task_queue(self) -> str:
        task_queue = getattr(settings, "DEPLOYMENTS_TASK_QUEUE", "")
        if not task_queue:
            raise WorkflowError("TemporalWorkflowAdapter is missing setting: DEPLOYMENTS_TASK_QUEUE.")
        return task_queue

    def _max_attempts(self) -> int:
        # Temporal-level retry budget for the workflow itself. Activity
        # retries inside the workflow are configured separately by the
        # worker. Defaults to the cluster-wide setting so this matches
        # the rest of PostHog's Temporal usage.
        return int(getattr(settings, "TEMPORAL_WORKFLOW_MAX_ATTEMPTS", "3"))

    def start_build(self, *, workflow_input: BuildInput) -> WorkflowHandle:
        task_queue = self._task_queue()
        max_attempts = self._max_attempts()
        workflow_id = f"deployment-{workflow_input.deployment_id}"

        try:
            client = sync_connect()
            handle: TemporalWorkflowHandle = asyncio.run(
                client.start_workflow(
                    DEPLOYMENT_BUILD_WORKFLOW,
                    workflow_input,
                    id=workflow_id,
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=max_attempts),
                )
            )
        except WorkflowAlreadyStartedError as err:
            # WorkflowAlreadyStartedError doesn't inherit from RPCError —
            # they share TemporalError as the common ancestor but sit on
            # different branches. Caught separately so a deterministic
            # workflow-id collision (HTTP retry, mid-transaction retry)
            # surfaces with a clear error rather than a 500.
            logger.info("temporal_start_workflow_already_started", workflow_id=workflow_id)
            raise WorkflowError(f"Deployment workflow already running: {err}") from err
        except RPCError as err:
            logger.warning("temporal_start_workflow_failed", workflow_id=workflow_id, error=str(err))
            raise WorkflowError(f"Failed to start deployment workflow: {err}") from err

        run_id = handle.result_run_id or handle.first_execution_run_id or ""
        if not run_id:
            # Temporal always returns one of these; the empty fallback
            # exists so the caller's persist step has something to write,
            # not because we expect to hit it.
            logger.warning("temporal_start_workflow_no_run_id", workflow_id=workflow_id)
        return WorkflowHandle(workflow_id=workflow_id, run_id=run_id)

    def signal_cancel(self, *, workflow_id: str) -> None:
        try:
            client = sync_connect()

            async def _cancel() -> None:
                handle = client.get_workflow_handle(workflow_id)
                await handle.cancel()

            asyncio.run(_cancel())
        except RPCError as err:
            # Workflow already finished or doesn't exist → not an error
            # from the user's perspective; the cancel is a no-op. Match
            # on the structured status code rather than the message text,
            # which can vary across SDK versions or locales. Other RPC
            # failures bubble up so the viewset can surface them.
            if err.status == RPCStatusCode.NOT_FOUND:
                logger.info("temporal_cancel_workflow_not_found", workflow_id=workflow_id)
                return
            logger.warning("temporal_cancel_workflow_failed", workflow_id=workflow_id, error=str(err))
            raise WorkflowError(f"Failed to cancel deployment workflow: {err}") from err


def get_workflow_adapter() -> WorkflowAdapter:
    """Resolve the adapter implementation from settings.

    Reads `settings.DEPLOYMENTS_WORKFLOW_ADAPTER` as a `"module.path:ClassName"`
    string; if unset, returns `NullWorkflowAdapter`. Wire the real
    implementation in by setting this env var to
    `products.deployments.backend.adapters.temporal:TemporalWorkflowAdapter`.
    """
    path = getattr(settings, "DEPLOYMENTS_WORKFLOW_ADAPTER", None)
    if not path:
        return NullWorkflowAdapter()
    module_path, class_name = path.split(":")
    module = import_module(module_path)
    return getattr(module, class_name)()
