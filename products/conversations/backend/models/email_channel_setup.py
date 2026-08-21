from django.db import models

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class EmailChannelSetupProvider(models.TextChoices):
    GOOGLE = "google", "Google"


class EmailChannelSetup(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    channel = models.OneToOneField(
        "conversations.EmailChannel",
        on_delete=models.CASCADE,
        related_name="setup",
    )
    provider = models.CharField(max_length=32, choices=EmailChannelSetupProvider.choices)
    expires_at = models.DateTimeField()
    confirmation_action = EncryptedTextField(null=True, blank=True)
    confirmation_message_id_hash = models.CharField(max_length=64, default="", blank=True)
    confirmation_received_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_email_channel_setup"
