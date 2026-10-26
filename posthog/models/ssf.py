from django.db import models

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.utils import UUIDModel


class SSFDirection(models.TextChoices):
    INCOMING = "incoming", "Incoming"
    OUTGOING = "outgoing", "Outgoing"


class SSFConfiguration(UUIDModel):
    organization = models.OneToOneField("posthog.Organization", on_delete=models.CASCADE, db_constraint=False)
    enabled = models.BooleanField(default=False)
    transmitter_audience = models.CharField(max_length=512, blank=True, default="")
    event_types = models.JSONField(default=list, blank=True)
    receiver_issuer = models.URLField(max_length=2048, blank=True, default="")
    receiver_audience = models.CharField(max_length=512, blank=True, default="")
    receiver_jwks = models.JSONField(default=dict, blank=True)
    receiver_stream_id = models.CharField(max_length=255, blank=True, default="")
    receiver_critical_subject_members = models.JSONField(default=list, blank=True)
    receiver_verification_state = EncryptedTextField(null=True, blank=True)
    receiver_token_hash = models.CharField(max_length=64, blank=True, default="")
    transmitter_token_hash = models.CharField(max_length=64, blank=True, default="")
    signing_key = EncryptedTextField(null=True, blank=True)
    signing_key_id = models.CharField(max_length=64, blank=True, default="")
    previous_public_keys = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class SSFConnection(UUIDModel):
    Direction = SSFDirection

    organization = models.ForeignKey("posthog.Organization", on_delete=models.CASCADE, db_constraint=False)
    name = models.CharField(max_length=200)
    direction = models.CharField(max_length=8, choices=Direction.choices)
    enabled = models.BooleanField(default=True)
    issuer = models.URLField(max_length=2048, blank=True, default="")
    audience = models.CharField(max_length=512, blank=True, default="")
    remote_token = EncryptedTextField(null=True, blank=True)
    token_hash = models.CharField(max_length=64, blank=True, default="")
    jwks_uri = models.URLField(max_length=2048, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    legacy_jwks = models.JSONField(default=dict, blank=True)
    discovered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "token_hash"],
                condition=~models.Q(token_hash=""),
                name="ssf_connection_unique_credential",
            )
        ]


class SSFStream(UUIDModel):
    class Status(models.TextChoices):
        ENABLED = "enabled", "Enabled"
        PAUSED = "paused", "Paused"
        DISABLED = "disabled", "Disabled"
        PROVISIONING = "provisioning", "Provisioning"
        FAILED = "failed", "Failed"

    organization = models.ForeignKey("posthog.Organization", on_delete=models.CASCADE, db_constraint=False)
    connection = models.ForeignKey(
        SSFConnection, on_delete=models.CASCADE, related_name="streams", null=True, blank=True
    )
    remote_stream_id = models.CharField(max_length=255, blank=True, default="")
    audiences = models.JSONField(default=list, blank=True)
    events_delivered = models.JSONField(default=list, blank=True)
    endpoint_url = models.URLField(max_length=2048, blank=True, default="")
    receiver_token_hash = models.CharField(max_length=64, blank=True, default="")
    receiver_token = EncryptedTextField(null=True, blank=True)
    verification_state = EncryptedTextField(null=True, blank=True)
    verification_requested_at = models.DateTimeField(null=True, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=1024, blank=True, default="")
    operation_until = models.DateTimeField(null=True, blank=True)
    retry_at = models.DateTimeField(null=True, blank=True)
    audience = models.CharField(max_length=512)
    events_requested = models.JSONField(default=list)
    description = models.CharField(max_length=1024, blank=True, default="")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ENABLED)
    reason = models.CharField(max_length=1024, blank=True, default="")
    subjects = EncryptedTextField(default="[]")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "remote_stream_id"],
                condition=~models.Q(remote_stream_id=""),
                name="ssf_stream_unique_remote",
            )
        ]


class SSFEvent(UUIDModel):
    Direction = SSFDirection

    organization = models.ForeignKey("posthog.Organization", on_delete=models.CASCADE, db_constraint=False)
    stream = models.ForeignKey(SSFStream, on_delete=models.SET_NULL, null=True, blank=True)
    direction = models.CharField(max_length=8, choices=Direction.choices)
    issuer_hash = models.CharField(max_length=64)
    jti = models.CharField(max_length=255)
    token = EncryptedTextField()
    first_delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "direction", "issuer_hash", "jti"], name="ssf_event_unique_jti"
            )
        ]
        indexes = [models.Index(fields=["stream", "created_at"], name="ssf_event_stream_created_idx")]
