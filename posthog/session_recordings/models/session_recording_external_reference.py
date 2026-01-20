from django.db import models

from posthog.models.integration import Integration
from posthog.models.utils import UUIDModel


class SessionRecordingExternalReference(UUIDModel):
    """
    Links a session recording to an external third party issue tracker
    Reuses the Integration model from error tracking for OAuth credentials.
    """

    session_recording = models.ForeignKey(
        "SessionRecording",
        on_delete=models.CASCADE,
        related_name="external_references",
        related_query_name="external_reference",
        db_index=True,
    )
    integration = models.ForeignKey(
        Integration,
        on_delete=models.CASCADE,
        related_name="external_references",
    )
    # Stores provider-specific data like issue ID, repository name, etc.
    # Examples:
    #   Linear: {'id': 'LINEAR-123'}
    external_context = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_sessionrecordingexternalreference"
