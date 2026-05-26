"""Temporal workflows and activities for the autoresearch inference pipeline.

`start_temporal_worker` imports WORKFLOWS and ACTIVITIES from here and
registers them on the `autoresearch-task-queue`.
"""

from .workflows import AutoresearchInferenceWorkflow, activity_load_champion, activity_run_inference

WORKFLOWS = [AutoresearchInferenceWorkflow]

ACTIVITIES = [
    activity_load_champion,
    activity_run_inference,
]

__all__ = ["ACTIVITIES", "WORKFLOWS", "AutoresearchInferenceWorkflow"]
