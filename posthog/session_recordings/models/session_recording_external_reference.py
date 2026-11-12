from django.db import models

from posthog.integrations import IntegrationRecord
from posthog.integrations.lifecycle import register_delete_hook
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
    #   Linear: {'id': 'LINEAR-123', 'title': '...'}
    #   GitHub: {'id': '#456', 'url': 'https://github.com/...', 'title': '...'}
    external_context = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_sessionrecordingexternalreference"


def delete_external_references_of_integration(row: IntegrationRecord) -> None:
    # Does the work of the CASCADE foreign key, which goes away when the rows leave this database.
    SessionRecordingExternalReference.objects.filter(integration_id=row.id).delete()


register_delete_hook(delete_external_references_of_integration)
