"""Map what Tasks reports for a run to the public status of a cloud agent run. Pure, no database."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from posthog.dataclasses import frozen

from ..facade.enums import CloudAgentRunStatus, CloudAgentRunStatusReason, CloudAgentSessionStatus

# The `source` that the quota sweep gives to Tasks when it cancels a run. Tasks stores it on the
# run, and it is the only record that the usage limit, and not a person, stopped the run.
QUOTA_SWEEP_CANCEL_SOURCE: Final = "cloud_agents_quota_sweep"

_WAITING_TASK_RUN_STATUSES: Final = ("not_started", "queued")
_ACTIVE_TASK_RUN_STATUS: Final = "in_progress"
_ENDED_TASK_RUN_STATUSES: Final = ("completed", "failed", "cancelled")

# Tasks has one set of ended statuses for `idle` and for `done`. The list reads the state of
# each ended task to tell the two apart.
_TASK_RUN_STATUSES_BY_STATUS: Final[dict[CloudAgentRunStatus, tuple[str, ...]]] = {
    CloudAgentRunStatus.QUEUED: _WAITING_TASK_RUN_STATUSES,
    CloudAgentRunStatus.RUNNING: (_ACTIVE_TASK_RUN_STATUS,),
    CloudAgentRunStatus.IDLE: _ENDED_TASK_RUN_STATUSES,
    CloudAgentRunStatus.DONE: _ENDED_TASK_RUN_STATUSES,
}

_REASON_BY_FAILED_RUN_END: Final[dict[str, CloudAgentRunStatusReason]] = {
    "timeout": CloudAgentRunStatusReason.TIMED_OUT,
    "usage_limit": CloudAgentRunStatusReason.CREDIT_SPENT,
    "error": CloudAgentRunStatusReason.UNEXPECTED_FAILURE,
}

# The error text of a Tasks run is written for the people who operate Tasks. It can hold an
# exception message or the name of another product, so the API shows one of these messages and
# never the Tasks text.
_DETAIL_BY_REASON: Final[dict[CloudAgentRunStatusReason, str]] = {
    CloudAgentRunStatusReason.PROVISION_FAILED: (
        "The run stopped because of a problem with the sandbox at PostHog. You are not charged for "
        "this sandbox time. Send a message to try again."
    ),
    CloudAgentRunStatusReason.UNEXPECTED_FAILURE: "The run failed. Send a message to try again, or start a new run.",
    CloudAgentRunStatusReason.TIMED_OUT: "The run stopped because it reached its time limit. Send a message to continue.",
    CloudAgentRunStatusReason.CREDIT_SPENT: (
        "The run stopped because this project reached its usage limit. "
        "Raise the limit in billing settings, then send a message to continue."
    ),
    CloudAgentRunStatusReason.FINISHED: "The pull request of the run was merged.",
    CloudAgentRunStatusReason.CLOSED: "Every pull request of the run was closed and not merged.",
}


@frozen
class RunStatus:
    """The public status of a run. `reason` is None while the run is queued or running."""

    status: CloudAgentRunStatus
    reason: CloudAgentRunStatusReason | None = None


def _completed_status(pull_request_states: Sequence[str | None]) -> RunStatus:
    if "merged" in pull_request_states:
        return RunStatus(status=CloudAgentRunStatus.DONE, reason=CloudAgentRunStatusReason.FINISHED)
    # A pull request with no known state can still be open, so only a full set of closed ones ends the run.
    if pull_request_states and all(state == "closed" for state in pull_request_states):
        return RunStatus(status=CloudAgentRunStatus.DONE, reason=CloudAgentRunStatusReason.CLOSED)
    return RunStatus(status=CloudAgentRunStatus.IDLE, reason=CloudAgentRunStatusReason.TURN_CLOSED)


def _failed_status(run_end: str | None, compute_waived: bool) -> RunStatus:
    if run_end is None:
        raise ValueError("A run that ended needs its end class")
    if run_end not in _REASON_BY_FAILED_RUN_END:
        raise ValueError(f"Unknown end {run_end!r} of a failed run")
    reason = _REASON_BY_FAILED_RUN_END[run_end]
    # Tasks waives the sandbox time only for a failure of PostHog infrastructure, so the waiver
    # is the record of that failure.
    if reason == CloudAgentRunStatusReason.UNEXPECTED_FAILURE and compute_waived:
        reason = CloudAgentRunStatusReason.PROVISION_FAILED
    return RunStatus(status=CloudAgentRunStatus.IDLE, reason=reason)


def _cancelled_status(cancel_source: str | None) -> RunStatus:
    # The project can get credit again, so a run that the quota sweep stopped can continue.
    if cancel_source == QUOTA_SWEEP_CANCEL_SOURCE:
        return RunStatus(status=CloudAgentRunStatus.IDLE, reason=CloudAgentRunStatusReason.CREDIT_SPENT)
    return RunStatus(status=CloudAgentRunStatus.DONE, reason=CloudAgentRunStatusReason.CANCELLED)


def run_status_for(
    task_run_status: str,
    *,
    run_end: str | None = None,
    cancel_source: str | None = None,
    compute_waived: bool = False,
    pull_request_states: Sequence[str | None] = (),
) -> RunStatus:
    """The public status of a run, from the latest Tasks run of its task.

    `run_end` is the Tasks class of the end, and `cancel_source` is the source of the cancel
    request that Tasks recorded, if there was one. `compute_waived` is True when Tasks does not
    bill the sandbox time of the run. `pull_request_states` holds one state for each pull request
    of the run, and None for a state that is not known. Raises `ValueError` for a status or an
    end that Tasks does not have.
    """
    if task_run_status in _WAITING_TASK_RUN_STATUSES:
        return RunStatus(status=CloudAgentRunStatus.QUEUED)
    if task_run_status == _ACTIVE_TASK_RUN_STATUS:
        return RunStatus(status=CloudAgentRunStatus.RUNNING)
    if task_run_status == "completed":
        return _completed_status(pull_request_states)
    if task_run_status == "failed":
        return _failed_status(run_end, compute_waived)
    if task_run_status == "cancelled":
        return _cancelled_status(cancel_source)
    raise ValueError(f"Unknown task run status {task_run_status!r}")


def session_status_for(task_run_status: str) -> CloudAgentSessionStatus:
    """The status of one agent session. Raises `ValueError` for a status that Tasks does not have."""
    if task_run_status in _WAITING_TASK_RUN_STATUSES:
        return CloudAgentSessionStatus.QUEUED
    if task_run_status == _ACTIVE_TASK_RUN_STATUS:
        return CloudAgentSessionStatus.RUNNING
    if task_run_status in _ENDED_TASK_RUN_STATUSES:
        return CloudAgentSessionStatus.ENDED
    raise ValueError(f"Unknown task run status {task_run_status!r}")


def task_run_statuses_for(status: CloudAgentRunStatus) -> tuple[str, ...]:
    """The Tasks run statuses that a run with `status` can have."""
    return _TASK_RUN_STATUSES_BY_STATUS[status]


def shares_task_run_statuses(status: CloudAgentRunStatus) -> bool:
    """Whether another public status has the same Tasks run statuses, so Tasks cannot filter by `status` alone."""
    statuses = _TASK_RUN_STATUSES_BY_STATUS[status]
    return any(other != status and _TASK_RUN_STATUSES_BY_STATUS[other] == statuses for other in CloudAgentRunStatus)


def status_detail_for(reason: CloudAgentRunStatusReason | None) -> str | None:
    """The message the API shows for a reason. None when the reason needs no explanation."""
    return _DETAIL_BY_REASON.get(reason) if reason is not None else None
