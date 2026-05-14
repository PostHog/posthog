"""Django models for agent_stack."""

from __future__ import annotations

from django.db import models

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.utils import UUIDModel

from .enums import DeploymentStatus, RevisionState, SandboxState


class AgentApplication(UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    slug = models.CharField(max_length=63)
    description = models.TextField(blank=True, default="")

    # Raw .env contents uploaded by the developer. Plaintext never returned by the
    # public API after creation; decryption is gated to the internal API used by
    # agent-runner, audit-logged per call.
    # null when no env is set — `EncryptedFieldMixin.get_prep_value` writes None for
    # falsy values, so a `default=""` would still hit a NOT NULL violation on insert.
    encrypted_env: EncryptedTextField = EncryptedTextField(null=True, blank=True)

    deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # Slug is the routing subdomain prefix — globally unique among live apps.
            # Partial uniqueness lets a deleted app's slug be reclaimed.
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(deleted=False),
                name="agent_stack_application_unique_active_slug",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "deleted"]),
        ]

    def __str__(self) -> str:
        return self.slug


class AgentApplicationRevision(UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    application = models.ForeignKey(AgentApplication, on_delete=models.CASCADE, related_name="revisions")

    state = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in RevisionState],
        default=RevisionState.PENDING_UPLOAD,
    )

    # How this revision serves traffic. Independent of `state` — a revision must reach
    # state=ready before logic promotes it to LIVE or PREVIEW. Uniqueness of LIVE per
    # application is enforced at the logic layer, not in the DB.
    deployment_status = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in DeploymentStatus],
        default=DeploymentStatus.DISABLED,
    )

    # Content-hash binding for the presigned PUT.
    bundle_s3_key = models.CharField(max_length=512, blank=True, default="")
    bundle_size = models.BigIntegerField(null=True, blank=True)
    bundle_sha256 = models.CharField(max_length=64, blank=True, default="")

    # Validated synchronously at deploy start.
    top_level_config = models.JSONField(default=dict)
    # Populated by the async validator; null until then. v1 reads top_level_config directly.
    parsed_manifest = models.JSONField(null=True, blank=True)
    # Structured errors when state=failed.
    validation_report = models.JSONField(null=True, blank=True)

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["application", "state", "-created_at"],
                name="agent_stack_revision_app_state",
            ),
            models.Index(
                fields=["application", "deployment_status"],
                name="agent_stack_rev_app_deploy",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.application_id}:{self.id} ({self.state})"


class AgentApplicationSandboxInstance(UUIDModel):
    """Modal sandbox tracker for (application, revision).

    v1 = at most one per (application, revision); not enforced at the DB level
    so v2 can grow concurrent sandboxes without a migration.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    application = models.ForeignKey(AgentApplication, on_delete=models.CASCADE, related_name="sandbox_instances")
    revision = models.ForeignKey(AgentApplicationRevision, on_delete=models.CASCADE)

    modal_sandbox_id = models.CharField(max_length=255, blank=True, default="")
    state = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in SandboxState],
        default=SandboxState.PROVISIONING,
    )

    error_message = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    terminated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["application", "revision", "state"],
                name="agent_stack_sandbox_lookup",
            ),
            models.Index(
                fields=["state", "last_used_at"],
                name="agent_stack_sandbox_reaper",
            ),
        ]

    def __str__(self) -> str:
        return f"sandbox:{self.modal_sandbox_id or self.id} ({self.state})"
