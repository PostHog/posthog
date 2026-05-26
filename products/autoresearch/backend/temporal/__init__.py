"""Temporal workflows and activities for autoresearch inference and validation.

`start_temporal_worker` imports WORKFLOWS and ACTIVITIES from here and
registers them on the `autoresearch-task-queue`.
"""

from .workflows import (
    AutoresearchInferenceWorkflow,
    AutoresearchValidationWorkflow,
    activity_load_champion,
    activity_run_inference,
    activity_run_validation,
)

WORKFLOWS = [AutoresearchInferenceWorkflow, AutoresearchValidationWorkflow]

ACTIVITIES = [
    activity_load_champion,
    activity_run_inference,
    activity_run_validation,
]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "AutoresearchInferenceWorkflow",
    "AutoresearchValidationWorkflow",
]
