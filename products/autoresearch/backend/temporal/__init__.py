"""Temporal workflows and activities for autoresearch inference, validation, and training.

`start_temporal_worker` imports WORKFLOWS and ACTIVITIES from here and
registers them on `settings.AUTORESEARCH_TASK_QUEUE`, which the
temporal-worker-self-driving fleet polls.
"""

from .workflows import (
    AutoresearchCoordinatorWorkflow,
    AutoresearchInferenceWorkflow,
    AutoresearchPropertyCleanupWorkflow,
    AutoresearchValidationWorkflow,
    activity_fail_cleanup_run,
    activity_fail_lost_inference_runs,
    activity_kickoff_training,
    activity_load_active_pipelines,
    activity_mark_daily_sweep,
    activity_remove_person_property,
    activity_run_inference,
    activity_run_shadow_scoring,
    activity_run_validation,
)

WORKFLOWS = [
    AutoresearchCoordinatorWorkflow,
    AutoresearchInferenceWorkflow,
    AutoresearchPropertyCleanupWorkflow,
    AutoresearchValidationWorkflow,
]

ACTIVITIES = [
    activity_fail_cleanup_run,
    activity_fail_lost_inference_runs,
    activity_kickoff_training,
    activity_load_active_pipelines,
    activity_mark_daily_sweep,
    activity_remove_person_property,
    activity_run_inference,
    activity_run_shadow_scoring,
    activity_run_validation,
]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "AutoresearchCoordinatorWorkflow",
    "AutoresearchInferenceWorkflow",
    "AutoresearchPropertyCleanupWorkflow",
    "AutoresearchValidationWorkflow",
]
