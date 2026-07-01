"""
Django models for the agent platform.

All agent-platform tables — authoring **and** runtime — live in a single
dedicated product database (`agent_platform`, routed via
`products/db_routing.yaml`). Django owns the schema and every migration; the
node services (`agent-{ingress,runner,janitor}`) are pure clients that connect
to this DB and run raw SQL — they no longer manage schema.

Because the DB is separate from the main posthog DB, models here cannot
ForeignKey `Team`/`User` (no cross-database FKs). They use plain id columns
(`team_id` via `ProductTeamModel`, `created_by_id`) and resolve those entities
through the facade when needed. ForeignKeys *between* agent models are fine —
they're all in the same DB.

NOTE: the skill / custom-tool template registry models (and their API surface)
were dropped pending a rethink — see the commented-out routes in `routes.py`.
"""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q, Value
from django.db.models.functions import Coalesce, Now

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.scoping.product_mixin import ProductTeamModel
from posthog.models.utils import UUIDModel

from .logic.generated import APPROVAL_REQUEST_STATES

REVISION_STATE_CHOICES = [
    ("draft", "draft"),
    ("ready", "ready"),
    ("live", "live"),
    ("archived", "archived"),
]

# Mirrors the JSONB default the node session writer relies on.
USAGE_TOTAL_DEFAULT = {
    "tokens_in": 0,
    "tokens_out": 0,
    "cache_read": 0,
    "cache_write": 0,
    "cost_input": 0,
    "cost_output": 0,
    "cost_cache_read": 0,
    "cost_cache_write": 0,
    "cost_total": 0,
}


# ─── Authoring ────────────────────────────────────────────────────────


class AgentApplication(ProductTeamModel, UUIDModel):
    """One agent. Slug is a single global namespace (server-minted on create,
    globally unique) so domain-mode ingress routing — `<slug>.agents.<suffix>`,
    which carries no team — resolves without knowing the team up front."""

    name = models.CharField(max_length=255)
    # SlugField adds Django's validate_slug ([a-zA-Z0-9_-]) so node-side writers
    # can't land a slug that later builds an unsafe preview-proxy URL.
    slug = models.SlugField(max_length=63)
    description = models.TextField(blank=True, default="", db_default="")

    live_revision = models.ForeignKey(
        "AgentRevision",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="live_for",
    )

    archived = models.BooleanField(default=False, db_default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    # No cross-DB FK to posthog.User — plain id, resolved via the facade.
    created_by_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        db_table = "agent_application"
        constraints = [
            models.UniqueConstraint(
                fields=["slug"],
                condition=Q(archived=False),
                name="agent_application_unique_active_slug",
            ),
        ]
        indexes = [
            models.Index(fields=["team_id", "archived"]),
        ]

    def __str__(self) -> str:
        return self.slug


class AgentRevision(ProductTeamModel, UUIDModel):
    """One revision of an agent. `spec` is structural; the bundle is content.

    State machine: draft → ready → live | archived.
    """

    # Django (authoring API) sets team_id on create; the node-side createRevision
    # (test harness) omits it, so allow null rather than force every node writer
    # to thread it. Django-created rows always carry it.
    team_id = models.BigIntegerField(db_index=True, null=True)  # type: ignore[assignment]  # nullable override of ProductTeamModel.team_id (node writers omit it)

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

    state = models.CharField(max_length=16, choices=REVISION_STATE_CHOICES, default="draft", db_default="draft")

    bundle_uri = models.TextField()
    bundle_sha256 = models.CharField(max_length=64, null=True, blank=True)

    spec = models.JSONField(default=dict)

    # Draft references to versioned skills in the llma-skill store. Each entry
    # is {from_template, alias, version?}. Freeze resolves them against the
    # store at the pinned version, materializes the skill (SKILL.md + any
    # companion files) into the bundle under skills/<alias>/, and stamps
    # provenance onto the frozen spec — so a frozen revision never re-resolves a
    # possibly-changed skill at runtime. Authoring-time only; carried forward
    # when a new draft is forked from a parent.
    skill_refs = models.JSONField(default=list, db_default=Value("[]"))

    # Encrypted JSON env block — the secret values this revision runs with.
    # Decrypted at runtime by the worker via `EncryptedFields` (see
    # services/agent-shared/src/runtime/encryption.ts). Lives on the revision
    # (not the application) so a draft can be previewed with its own secret
    # values without touching the live revision's, and a promote carries the
    # secrets it was tested with. Mutable in place (key rotation must not
    # require cutting a new revision) and copied forward when a new draft is
    # forked from a parent. NULL means "no secrets set".
    encrypted_env: EncryptedTextField = EncryptedTextField(null=True, blank=True)

    created_by_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        db_table = "agent_revision"
        indexes = [
            models.Index(fields=["application", "state"]),
            models.Index(fields=["state", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.application_id}@{str(self.id)[:8]} ({self.state})"


# ─── Runtime ──────────────────────────────────────────────────────────
#
# Written by the node services via raw SQL (PgSessionQueue, etc.). Django
# owns the schema; `db_default` reproduces the Postgres-level defaults the
# node inserts may omit. Cross-table refs to authoring use plain UUID columns
# (no FK) so authoring and runtime stay loosely coupled even though they're
# co-located.


class AgentSession(ProductTeamModel, UUIDModel):
    """A single agent run. High-churn — claimed, driven, persisted by the runner."""

    application_id = models.UUIDField()
    revision_id = models.UUIDField()
    external_key = models.TextField(null=True, blank=True)
    idempotency_key = models.TextField(null=True, blank=True)
    trigger_metadata = models.JSONField(null=True, blank=True)
    state = models.TextField(default="queued", db_default="queued")
    conversation = models.JSONField(default=list, db_default=Value("[]"))
    pending_inputs = models.JSONField(default=list, db_default=Value("[]"))
    principal = models.JSONField(null=True, blank=True)
    acl = models.JSONField(default=list, db_default=Value("[]"))
    pending_elevation_requests = models.JSONField(default=list, db_default=Value("[]"))
    claimed_at = models.DateTimeField(null=True, blank=True)
    retry_count = models.IntegerField(default=0, db_default=0)
    usage_total = models.JSONField(
        default=dict,
        db_default=Value(
            '{"tokens_in": 0, "tokens_out": 0, "cache_read": 0, "cache_write": 0, "cost_input": 0, "cost_output": 0, "cost_cache_read": 0, "cost_cache_write": 0, "cost_total": 0}'
        ),
    )
    # Derived on every conversation write by the node SessionQueue so the list
    # view + search never read the full `conversation` JSONB. search_text is a
    # truncated user+assistant text digest; turn_count is len(conversation).
    search_text = models.TextField(null=True, blank=True)
    turn_count = models.IntegerField(default=0, db_default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        db_table = "agent_session"
        indexes = [
            models.Index(fields=["state", "created_at"], name="agent_sess_created_idx"),
            models.Index(fields=["state", "updated_at"], name="agent_sess_updated_idx"),
            models.Index(
                fields=["application_id", "external_key"],
                name="agent_sess_extkey_idx",
                condition=Q(external_key__isnull=False),
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["application_id", "idempotency_key"],
                condition=Q(idempotency_key__isnull=False),
                name="agent_session_idempotency_key_unique",
            ),
        ]


class AgentUser(ProductTeamModel, UUIDModel):
    """External principal an agent has talked to (Slack user, etc.)."""

    application_id = models.UUIDField()
    principal_kind = models.TextField()
    principal_id = models.TextField()
    metadata = models.JSONField(default=dict, db_default=Value("{}"))
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        db_table = "agent_user"
        constraints = [
            models.UniqueConstraint(
                fields=["application_id", "principal_kind", "principal_id"],
                name="agent_user_unique_natural_key",
            ),
        ]


class AgentSandboxInstance(ProductTeamModel, UUIDModel):
    """A provisioned sandbox (Docker/Modal) backing a session's tool execution."""

    application_id = models.UUIDField()
    revision_id = models.UUIDField()
    session_id = models.UUIDField(null=True, blank=True)
    provider_kind = models.TextField()
    provider_sandbox_id = models.TextField(default="", db_default="")
    state = models.TextField(default="provisioning", db_default="provisioning")
    error_message = models.TextField(default="", db_default="")
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    last_used_at = models.DateTimeField(null=True, blank=True)
    terminated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "agent_sandbox_instance"
        indexes = [
            models.Index(
                Coalesce("last_used_at", "created_at"),
                "state",
                name="asi_state_idx",
            ),
            models.Index(
                fields=["session_id"],
                name="asi_session_idx",
                condition=Q(session_id__isnull=False),
            ),
        ]


class AgentToolApprovalRequest(ProductTeamModel, UUIDModel):
    """One intercepted approval-gated tool call awaiting a decision."""

    session_id = models.UUIDField()
    application_id = models.UUIDField()
    revision_id = models.UUIDField()
    turn = models.IntegerField()
    tool_call_id = models.TextField()
    tool_name = models.TextField()
    proposed_args = models.JSONField()
    args_hash = models.BinaryField()
    assistant_message = models.JSONField()
    approver_scope = models.JSONField()
    state = models.TextField()
    decision_by = models.UUIDField(null=True, blank=True)
    decision_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(null=True, blank=True)
    decided_args = models.JSONField(null=True, blank=True)
    dispatch_outcome = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "agent_tool_approval_request"
        constraints = [
            models.CheckConstraint(
                name="agent_tool_approval_request_state_valid",
                # Vocabulary owned by the runner (approval-store.ts). Imported from
                # the generated artifact so the DB CHECK can't drift from the states
                # the runner actually writes — a mismatch would reject a live insert.
                condition=Q(state__in=APPROVAL_REQUEST_STATES),
            ),
            models.UniqueConstraint(
                fields=["session_id", "tool_name", "args_hash"],
                condition=Q(state="queued"),
                name="agent_tool_approval_request_queued_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["state", "expires_at"], name="atar_expiry_idx"),
            models.Index(fields=["team_id", "state", "-created_at"], name="atar_team_idx"),
            models.Index(fields=["application_id", "state", "-created_at"], name="atar_app_idx"),
            models.Index(fields=["session_id", "-created_at"], name="atar_session_idx"),
        ]


class AgentSessionCredential(ProductTeamModel):
    """Per-session, TTL'd, encrypted-at-rest credential bag. Keyed 1:1 by session."""

    # The node credential broker upserts by session_id only (no team_id in hand);
    # the row is already team-scoped via its session. Allow null.
    team_id = models.BigIntegerField(db_index=True, null=True)  # type: ignore[assignment]  # nullable override of ProductTeamModel.team_id (node writers omit it)
    session_id = models.UUIDField(primary_key=True)
    encrypted_credentials = models.TextField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        db_table = "agent_session_credential"
        indexes = [
            models.Index(fields=["expires_at"], name="asc_expires_idx"),
        ]


class AgentIdentityCredential(ProductTeamModel, UUIDModel):
    """Persistent, per-principal, encrypted-at-rest linked credential.

    The "stored auth" an agent_user has consented to — e.g. a Slack user who
    OAuth-linked their PostHog (or GitHub, …) account. Keyed by (agent_user,
    provider). Read at turn start and copied into the ephemeral per-session
    AgentSessionCredential broker; never read directly by tools.
    """

    application_id = models.UUIDField()
    # The principal this credential belongs to (agent_user.id). Plain id, not a
    # FK — consistent with the loose coupling the runtime tables use elsewhere.
    agent_user_id = models.UUIDField()
    provider = models.TextField()  # "posthog" | "github" | "dogs" | ...
    # Fernet JSON: {access_token, refresh_token?, token_type?, expires_at?}.
    encrypted_credentials = models.TextField()
    # Granted scopes — not secret, kept plaintext for debugging without decrypt.
    scopes = ArrayField(models.TextField(), default=list, db_default=Value("{}"))
    state = models.TextField(default="active", db_default="active")  # active | revoked
    access_expires_at = models.DateTimeField(null=True, blank=True)
    # The proven external identity this link established (e.g. the PostHog user
    # uuid from /oauth/userinfo). Set only by an identity-establishing provider;
    # null for capability-only links. Replaces the old AgentUser.posthog_user_id —
    # per-asker auth reads it to resolve the PostHog user behind a principal.
    subject = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "agent_identity_credential"
        constraints = [
            models.UniqueConstraint(
                fields=["agent_user_id", "provider"],
                name="agent_identity_credential_unique_user_provider",
            ),
        ]
        indexes = [
            models.Index(fields=["application_id"], name="aic_application_idx"),
        ]


class AgentIdentityLinkState(ProductTeamModel, UUIDModel):
    """Single-use, short-TTL state row for an in-flight OAuth link.

    Binds one authorize round-trip to (agent_user, provider) so the callback
    can't be replayed or retargeted at a different principal. `used_at` enforces
    single use; `expires_at` bounds the window (≤10m). `code_verifier` is the
    PKCE verifier, server-side only.
    """

    application_id = models.UUIDField()
    agent_user_id = models.UUIDField()
    provider = models.TextField()
    scopes = ArrayField(models.TextField(), default=list, db_default=Value("{}"))
    # Stored plaintext, unlike the Fernet-encrypted agent_identity_credential.
    # Intentional: a PKCE verifier is single-use, ≤10m TTL, and worthless without
    # the matching authorization code — its secrecy rests on DB access control,
    # which is sufficient for a short-lived link-handshake secret.
    code_verifier = models.TextField()
    redirect_uri = models.TextField()
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        db_table = "agent_identity_link_state"
        indexes = [
            models.Index(fields=["expires_at"], name="ails_expires_idx"),
        ]
