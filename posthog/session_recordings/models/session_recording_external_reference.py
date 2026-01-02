from django.db import models

from posthog.models.integration import Integration
from posthog.models.utils import UUIDTModel


class SessionRecordingExternalReference(UUIDTModel):
    """
    Links a session recording to an external issue tracker (GitHub, Linear, GitLab, etc.)
    Reuses the Integration model from error tracking for OAuth credentials.
    """

    session_recording = models.ForeignKey(
        "SessionRecording",
        on_delete=models.CASCADE,
        related_name="external_references",
        related_query_name="external_reference",
    )
    integration = models.ForeignKey(
        Integration,
        on_delete=models.CASCADE,
    )
    # Stores provider-specific data like issue ID, repository name, etc.
    # Examples:
    #   Linear: {'id': 'LINEAR-123'}
    #   GitHub: {'repository': 'posthog', 'number': 456}
    #   GitLab: {'issue_id': 789}
    external_context = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_sessionrecordingexternalreference"
