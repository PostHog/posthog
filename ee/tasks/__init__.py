from ee.session_recordings.persistence_tasks import (
    persist_finished_recordings,
    persist_single_recording,
)
from .subscriptions import (
    deliver_subscription_report,
    handle_subscription_value_change,
    schedule_all_subscriptions,
)
from .replay_summaries import embed_batch_of_recordings_task, generate_recordings_embeddings_batch

# As our EE tasks are not included at startup for Celery, we need to ensure they are declared here so that they are imported by posthog/settings/celery.py

__all__ = [
    "persist_single_recording",
    "persist_finished_recordings",
    "schedule_all_subscriptions",
    "deliver_subscription_report",
    "handle_subscription_value_change",
    "embed_batch_of_recordings_task",
    "generate_recordings_embeddings_batch",
]
