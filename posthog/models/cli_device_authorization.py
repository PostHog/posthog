from django.db import models

from posthog.helpers.encrypted_fields import EncryptedCharField
from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class CLIDeviceAuthorization(TeamScopedRootMixin):
    class Status(models.TextChoices):
        PENDING = "pending"
        AUTHORIZED = "authorized"
        CONSUMED = "consumed"

    device_code = models.CharField(max_length=64, unique=True)
    user_code = models.CharField(max_length=9, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    user_id = models.BigIntegerField(null=True)
    team = models.ForeignKey(
        "posthog.Team",
        db_constraint=False,
        null=True,
        on_delete=models.CASCADE,
        related_name="cli_device_authorizations",
    )
    scopes = models.JSONField(default=list)
    label = models.CharField(max_length=40, blank=True)
    personal_api_key_value = EncryptedCharField(max_length=255, null=True, blank=True)
    expires_at = models.DateTimeField()
    authorized_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["expires_at"])]
