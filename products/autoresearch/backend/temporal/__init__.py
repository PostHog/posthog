"""Temporal workflows and activities for autoresearch inference, validation, and training.

`start_temporal_worker` imports WORKFLOWS and ACTIVITIES from here and
registers them on the `autoresearch-task-queue`.
"""

from .workflows import (
    AutoresearchCoordinatorWorkflow,
    AutoresearchInferenceWorkflow,
    AutoresearchValidationWorkflow,
    activity_kickoff_training,
    activity_load_active_pipelines,
    activity_load_champion,
    activity_run_inference,
    activity_run_validation,
)

WORKFLOWS = [
    AutoresearchCoordinatorWorkflow,
    AutoresearchInferenceWorkflow,
    AutoresearchValidationWorkflow,
]

ACTIVITIES = [
    activity_kickoff_training,
    activity_load_active_pipelines,
    activity_load_champion,
    activity_run_inference,
    activity_run_validation,
]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "AutoresearchCoordinatorWorkflow",
    "AutoresearchInferenceWorkflow",
    "AutoresearchValidationWorkflow",
]
