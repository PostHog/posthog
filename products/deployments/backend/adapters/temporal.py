"""Temporal workflow adapter boundary.

Build/Infra stream owns the real implementation (a thin wrapper around
the Temporal Python SDK). We declare the Protocol they implement against
and a Null stub for tests.

We only ever:
- Start a build workflow when a Deployment is created (one `start_build`
  call per new row).
- Signal cancellation when the user clicks Cancel on a non-terminal
  deployment (`signal_cancel`).

The workflow itself posts status transitions and events back to our
internal API — we never poll Temporal.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Protocol

from django.conf import settings

from ..domain.contracts import BuildInput


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


def get_workflow_adapter() -> WorkflowAdapter:
    path = getattr(settings, "DEPLOYMENTS_WORKFLOW_ADAPTER", None)
    if not path:
        return NullWorkflowAdapter()
    module_path, class_name = path.split(":")
    module = import_module(module_path)
    return getattr(module, class_name)()
