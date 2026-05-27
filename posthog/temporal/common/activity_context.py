"""Helpers for safely accessing Temporal activity context from code that may
also run outside an activity (e.g. tests, deferred-run replay, local CLI tools).

`activity.info()` raises `RuntimeError` when called outside an activity worker
thread. These wrappers translate that into `None` so callers can pass the value
through to downstream APIs that accept it as optional metadata.
"""

from __future__ import annotations

from temporalio import activity


def current_workflow_id() -> str | None:
    """Return the current Temporal workflow id, or None if not inside an activity."""
    try:
        return activity.info().workflow_id
    except RuntimeError:
        return None


def current_workflow_run_id() -> str | None:
    """Return the current Temporal workflow run id, or None if not inside an activity."""
    try:
        return activity.info().workflow_run_id
    except RuntimeError:
        return None
