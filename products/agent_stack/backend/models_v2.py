"""
Django models for the v2 agent platform refactor (see docs/native-refactor.md §1).

These replace the existing models.py shapes. Pre-prod cutover: drop the existing
tables and run a fresh migration from these. Keep the AgentApplication.encrypted_env
field for team secrets; everything else is fresh.

Notable shape changes from v1:
  - `AgentRevision.spec` (JSONB) is the structural truth — model, triggers, tools,
    skills, integrations, secrets, limits, entrypoint.
  - `AgentRevision.bundle_uri` (text) points to the S3 prefix holding the content
    bundle (agent.md, skills/, tools/<id>/source.ts + compiled.js, etc.).
  - `AgentRevision.bundle_sha256` is null until promote(), then immutable.
  - No `parsed_manifest`, no `top_level_config` — the spec IS the structural truth.
  - State machine: draft → ready → live | archived. No PENDING_UPLOAD.
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


SESSION_STATE_CHOICES = [
    ("queued", "queued"),
    ("running", "running"),
    ("waiting", "waiting"),
    ("completed", "completed"),
    ("failed", "failed"),
]


class AgentApplicationV2(UUIDModel):
    """One agent. Identified by (team, slug). Holds team secrets."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="agent_apps_v2")
    name = models.CharField(max_length=255)
    slug = models.CharField(max_length=63)
    description = models.TextField(blank=True, default="")

    encrypted_env: EncryptedTextField = EncryptedTextField(null=True, blank=True)

    live_revision = models.ForeignKey(
        "AgentRevisionV2",
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
        db_table = "agent_stack_application_v2"
        constraints = [
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(archived=False),
                name="agent_stack_application_v2_unique_active_slug",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "archived"]),
        ]

    def __str__(self) -> str:
        return self.slug


class AgentRevisionV2(UUIDModel):
    """One revision of an agent. Spec is structural; bundle is content."""

    application = models.ForeignKey(
        AgentApplicationV2,
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

    # S3 prefix holding the bundle directory (mutable while draft, frozen+stamped on promote).
    bundle_uri = models.TextField()
    # Null until promote(). Once set, the bundle is immutable.
    bundle_sha256 = models.CharField(max_length=64, null=True, blank=True)

    # Structural layer — see docs/native-refactor.md §1 for the JSON shape.
    spec = models.JSONField(default=dict)

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "agent_stack_revision_v2"
        indexes = [
            models.Index(fields=["application", "state"]),
            models.Index(fields=["state", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.application.slug}@{str(self.id)[:8]} ({self.state})"


class AgentSessionV2(UUIDModel):
    """One run of an agent, started by a trigger and consumed by the runner."""

    application = models.ForeignKey(
        AgentApplicationV2,
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    revision = models.ForeignKey(
        AgentRevisionV2,
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    state = models.CharField(max_length=16, choices=SESSION_STATE_CHOICES, default="queued")

    # Slack thread_ts, webhook x-external-key, etc. NULL = no dedupe key.
    # The combination (application, external_key) selects "the live session for this thread".
    external_key = models.CharField(max_length=255, null=True, blank=True)

    # The conversation, persisted across turns. Schema is whatever pi.dev consumes
    # (see ConversationMessage in @posthog/agent-shared-v2).
    conversation = models.JSONField(default=list)

    # Per-session bookkeeping — turns consumed, last error, etc.
    metadata = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "agent_stack_session_v2"
        indexes = [
            # Janitor sweep: find stuck sessions.
            models.Index(fields=["state", "updated_at"]),
            # Queue claim: pop next pending session.
            models.Index(fields=["state", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["application", "external_key"],
                condition=models.Q(state__in=["queued", "running", "waiting"]),
                name="agent_stack_session_v2_one_live_per_external_key",
            ),
        ]
