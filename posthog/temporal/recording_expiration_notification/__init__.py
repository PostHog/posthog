from posthog.temporal.recording_expiration_notification.activities import (
    generate_notifications,
    query_organizations,
    query_recordings,
    send_notifications,
)
from posthog.temporal.recording_expiration_notification.workflows import SendExpirationNotificationsWorkflow

WORKFLOWS = [
    SendExpirationNotificationsWorkflow,
]

ACTIVITIES = [query_organizations, query_recordings, generate_notifications, send_notifications]
