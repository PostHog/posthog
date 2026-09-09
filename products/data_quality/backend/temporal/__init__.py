"""Temporal wiring for data_quality. Registered on the data-modeling task queue."""

from collections.abc import Callable
from typing import Any

from posthog.temporal.common.base import PostHogWorkflow

from .activities.claim_due_schedules import acknowledge_schedule_activity, claim_due_schedules_activity
from .activities.cleanup import cleanup_check_runs_activity
from .activities.finalize_check_suite import (
    finalize_check_suite_activity,
    mark_check_suite_empty_activity,
    mark_check_suite_failed_activity,
)
from .activities.materialization_gate import materialization_gate_activity
from .activities.prepare_check_suite import prepare_check_suite_activity
from .activities.run_check_batch import run_check_batch_activity
from .workflows.cleanup import CleanupCheckRunsWorkflow
from .workflows.dispatch_scheduled_suites import DispatchScheduledSuitesWorkflow
from .workflows.run_check_suite import RunCheckSuiteWorkflow

WORKFLOWS: list[type[PostHogWorkflow]] = [
    RunCheckSuiteWorkflow,
    CleanupCheckRunsWorkflow,
    DispatchScheduledSuitesWorkflow,
]

ACTIVITIES: list[Callable[..., Any]] = [
    materialization_gate_activity,
    prepare_check_suite_activity,
    run_check_batch_activity,
    finalize_check_suite_activity,
    mark_check_suite_empty_activity,
    mark_check_suite_failed_activity,
    cleanup_check_runs_activity,
    claim_due_schedules_activity,
    acknowledge_schedule_activity,
]

__all__ = ["ACTIVITIES", "WORKFLOWS"]
