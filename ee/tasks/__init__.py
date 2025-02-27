from ee.session_recordings.persistence_tasks import (
    persist_finished_recordings,
    persist_single_recording,
)
from .subscriptions import (
    deliver_subscription_report,
    handle_subscription_value_change,
    schedule_all_subscriptions,
)
from ee.session_recordings.playlist_counters.recordings_that_match_playlist_filters import (
    count_recordings_that_match_playlist_filters,
    enqueue_recordings_that_match_playlist_filters,
)

# As our EE tasks are not included at startup for Celery, we need to ensure they are declared here so that they are imported by posthog/settings/celery.py

__all__ = [
    "persist_single_recording",
    "persist_finished_recordings",
    "schedule_all_subscriptions",
    "deliver_subscription_report",
    "handle_subscription_value_change",
    "count_recordings_that_match_playlist_filters",
    "enqueue_recordings_that_match_playlist_filters",
]
