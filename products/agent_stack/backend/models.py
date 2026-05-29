"""
Django models for the agent platform — the *authoring* surface.

Only the **definition** of an agent lives in the main Django/Postgres DB:
    - AgentApplication (one agent, identified by team + slug; holds secrets)
    - AgentRevision (one version of an agent — bundle + spec)

Everything the agent *creates at runtime* (sessions, identities of external
users it talks to, sandbox instances) lives in a separate node-managed
queue DB whose schema is owned by `services/agent-migrations/`. Those
tables are high-churn — keeping them out of the main DB shields the
rest of the product from agent-runtime write load.

Reads from the runtime DB happen through node-side HTTP (the janitor's
`/sessions/:id`, the ingress `/listen` SSE stream).
"""

from __future__ import annotations

from django.db import models

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.utils import UUIDModel

REVISION_STATE_CHOICES = [
    ("draft", "draft"),
    ("ready", "ready"),
    ("live", "live"),
    ("archived", "archived"),
]


class AgentApplication(UUIDModel):
    """One agent. Identified by (team, slug). Holds team secrets."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="agent_apps")
    name = models.CharField(max_length=255)
    slug = models.CharField(max_length=63)
    description = models.TextField(blank=True, default="")

    # Encrypted JSON env block. Decrypted at runtime by the worker via
    # `EncryptedFields` (see services/agent-shared/src/runtime/encryption.ts).
    encrypted_env: EncryptedTextField = EncryptedTextField(null=True, blank=True)

    live_revision = models.ForeignKey(
        "AgentRevision",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="live_for",
    )

    archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "agent_application"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "slug"],
                condition=models.Q(archived=False),
                name="agent_application_unique_active_slug",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "archived"]),
        ]

    def __str__(self) -> str:
        return self.slug


class AgentRevision(UUIDModel):
    """One revision of an agent. `spec` is structural; the bundle is content.

    State machine: draft → ready → live | archived. Mutability follows state:
    `draft` revisions accept spec edits and bundle re-uploads; once promoted
    to `ready` (bundle frozen, sha256 stamped) the spec and bundle are immutable.
    """

    application = models.ForeignKey(
        AgentApplication,
        on_delete=models.CASCADE,
        related_name="revisions",
    )
    parent_revision = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )

    state = models.CharField(max_length=16, choices=REVISION_STATE_CHOICES, default="draft")

    # S3/FS prefix holding the bundle directory (mutable while draft, frozen on promote).
    bundle_uri = models.TextField()
    # Null until the bundle is frozen. Once set, the bundle is immutable.
    bundle_sha256 = models.CharField(max_length=64, null=True, blank=True)

    # Structural spec — see docs/native-refactor.md §1 for the JSON shape.
    spec = models.JSONField(default=dict)

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "agent_revision"
        indexes = [
            models.Index(fields=["application", "state"]),
            models.Index(fields=["state", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.application.slug}@{str(self.id)[:8]} ({self.state})"
