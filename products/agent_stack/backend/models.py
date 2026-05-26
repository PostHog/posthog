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


class IdentitySpace(UUIDModel):
    """A directory of end-user records (`AgentUser`) attached to one or more
    agents. Stateful — lifecycle is independent of any stack, so `ass deploy`
    creating one then later being removed never destroys the space or its
    users. Team-scoped; agents in any stack within the same team can attach
    by name. See agent-stack/docs/auth-and-identity.md Layer 3.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=63)

    deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # Name is the local alias agents reference in `identity.space`.
            # Partial uniqueness lets a soft-deleted space's name be reclaimed.
            models.UniqueConstraint(
                fields=["team", "name"],
                condition=models.Q(deleted=False),
                name="agent_stack_identityspace_unique_active_name",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "deleted"], name="agent_stack_idspace_team"),
        ]

    def __str__(self) -> str:
        return f"{self.team_id}:{self.name}"


class AgentUser(UUIDModel):
    """The stable internal identifier for an end-user inside an `IdentitySpace`.
    v1 stores no PII — just the bare `(id, space)` mapping. Provider-asserted
    profile data flows through `ResolvedIdentity.profile` on the interface
    but is intentionally not persisted (see the PII / GDPR open question in
    auth-and-identity.md).
    """

    space = models.ForeignKey(IdentitySpace, on_delete=models.CASCADE, related_name="users")

    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["space", "-last_seen_at"], name="agent_stack_user_seen"),
        ]

    def __str__(self) -> str:
        return f"user:{self.id}"


class UserIdentity(UUIDModel):
    """Mapping from a provider-asserted `(provider, account, subject)` tuple
    to an `AgentUser`. A single user can hold many identities (Slack today, a
    native account tomorrow) — that's how the deferred native-auth merge
    stays additive. See auth-and-identity.md.
    """

    space = models.ForeignKey(IdentitySpace, on_delete=models.CASCADE, related_name="identities")
    user = models.ForeignKey(AgentUser, on_delete=models.CASCADE, related_name="identities")

    provider = models.CharField(max_length=63)
    provider_account_id = models.CharField(max_length=255)
    provider_subject = models.CharField(max_length=255)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # `(provider, account, subject)` is the permanent identity key
            # within a space — see "Settled decisions" in auth-and-identity.md.
            models.UniqueConstraint(
                fields=["space", "provider", "provider_account_id", "provider_subject"],
                name="agent_stack_useridentity_unique_tuple",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.provider_account_id}:{self.provider_subject}"


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
