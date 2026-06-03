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

from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import UUIDModel

REVISION_STATE_CHOICES = [
    ("draft", "draft"),
    ("ready", "ready"),
    ("live", "live"),
    ("archived", "archived"),
]


class AgentApplication(ModelActivityMixin, UUIDModel):
    """One agent. Identified by (team, slug). Holds team secrets.

    Activity logged via `ModelActivityMixin`: every save fires
    `model_activity_signal` and the receiver in
    `products.agent_platform.backend.activity` writes to the central
    activity log. Soft-delete via `archived=True` shows up there as an
    `updated` entry diffing the archived flag — no separate delete signal.
    """

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


class AgentRevision(ModelActivityMixin, UUIDModel):
    """One revision of an agent. `spec` is structural; the bundle is content.

    State machine: draft → ready → live | archived. Mutability follows state:
    `draft` revisions accept spec edits and bundle re-uploads; once promoted
    to `ready` (bundle frozen, sha256 stamped) the spec and bundle are immutable.

    Activity logged via `ModelActivityMixin`: spec edits and state
    transitions both surface as `updated` entries with field-level diffs.
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


# ─── Tools & Skills registry ──────────────────────────────────────────
#
# Shared, versioned skill markdown + custom-tool sources that agents
# pin into their frozen bundles at freeze time. See
# `docs/agent-platform/plans/skill-templates.md` for the full design.
#
# Versioning is append-only: each publish creates a new row with
# `version+1` and flips the prior row's `is_latest` to False. The
# partial unique index on (team, name) WHERE deleted=false AND
# is_latest=true enforces a single current version per (team, name).
#
# `team_id` is nullable so we can carry PostHog-canonical templates
# (`@posthog/<name>`) as global rows.


class AgentSkillTemplate(ModelActivityMixin, UUIDModel):
    """Shared markdown skill — one version per row.

    Pinned by agents via `spec.skills[].from_template`. At freeze time
    the janitor copies `body` into `bundle/skills/<alias>.md` and
    inserts an `AgentRevisionSkillTemplate` row so the relationship is
    queryable + FK-checked once the revision is immutable.
    """

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="agent_skill_templates",
        null=True,
        blank=True,
    )

    # Slug — lowercase a-z 0-9 hyphen, no consecutive hyphens. Enforced
    # by the serializer's regex (mirrors LLMSkill's pattern). `@posthog/`
    # prefix is reserved for canonical (team_id NULL) rows. Length caps at
    # 64 to match the Agent Skills spec `name` constraint — note the
    # registry `name` (which may carry the `@posthog/` prefix) is the
    # registry identity, distinct from the spec `name` emitted into the
    # frozen SKILL.md, which is the bundle-dir alias (a bare slug).
    name = models.CharField(max_length=64)
    # 1024 cap mirrors the Agent Skills spec `description` constraint.
    description = models.CharField(max_length=1024, blank=True, default="")

    # The SKILL.md body — what gets copied into the bundle as the index
    # file when an agent pins this template.
    body = models.TextField(blank=True, default="")

    # Versioning.
    version = models.PositiveIntegerField(default=1)
    is_latest = models.BooleanField(default=True)

    # First-class Agent Skills frontmatter fields, promoted out of the
    # free-form `metadata` bag so the registry UI + spec validator can
    # treat them specially and freeze can emit them into the SKILL.md
    # frontmatter. `license` is unbounded by the spec; `compatibility`
    # caps at 500.
    license = models.CharField(max_length=256, blank=True, default="", db_default="")
    compatibility = models.CharField(max_length=500, blank=True, default="", db_default="")

    # Free-form bag — agentskills.io-compatible `metadata` map (string →
    # string). Carries non-promoted keys like `version`, `author`. Not
    # interpreted by the platform.
    metadata = models.JSONField(default=dict, blank=True)

    # Optional explicit list of tool ids the skill expects to be wired
    # up. Honest declaration; the platform doesn't enforce it but
    # surfaces it in the registry UI.
    allowed_tools = models.JSONField(default=list, blank=True)

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    deleted = models.BooleanField(default=False)

    class Meta:
        db_table = "agent_skill_template"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name", "version"],
                condition=models.Q(deleted=False),
                name="agent_skill_template_unique_version_per_name",
            ),
            models.UniqueConstraint(
                fields=["team", "name"],
                condition=models.Q(deleted=False, is_latest=True),
                name="agent_skill_template_unique_latest_per_name",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "deleted"]),
            models.Index(fields=["name"]),
        ]

    def __str__(self) -> str:
        return f"{self.name}@v{self.version}"


class AgentSkillTemplateFile(UUIDModel):
    """Companion file inside a skill folder.

    Path is relative to the skill root and copied to
    `bundle/skills/<alias>/<path>` at freeze time. Multi-file skills
    enable patterns like `examples/<scenario>.md` or
    `templates/<shape>.json` without bloating the main body.
    """

    template = models.ForeignKey(
        AgentSkillTemplate,
        on_delete=models.CASCADE,
        related_name="files",
    )
    path = models.CharField(max_length=512)
    content = models.TextField(blank=True, default="")
    content_type = models.CharField(max_length=128, default="text/plain")

    class Meta:
        db_table = "agent_skill_template_file"
        constraints = [
            models.UniqueConstraint(
                fields=["template", "path"],
                name="agent_skill_template_file_unique_path",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.template_id}:{self.path}"


class AgentCustomToolTemplate(ModelActivityMixin, UUIDModel):
    """Shared TypeScript tool — one version per row.

    Same shape as skill templates but carries a (`source`, `compiled_js`)
    pair and an args schema instead of markdown. The bundler runs at
    publish time so freeze is a cheap copy step.
    """

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="agent_custom_tool_templates",
        null=True,
        blank=True,
    )

    name = models.CharField(max_length=128)
    description = models.CharField(max_length=4096, blank=True, default="")

    # The two artifacts the runner needs to execute the tool.
    source = models.TextField(blank=True, default="")
    compiled_js = models.TextField(blank=True, default="")

    # TypeBox / JSON Schema for the tool's args. Authoring + the runner
    # both validate against this.
    args_schema = models.JSONField(default=dict)
    # Informational — not enforced at runtime today.
    returns_schema = models.JSONField(default=dict, blank=True)

    # Explicit declaration of secret names the tool reads via
    # `ctx.secret(...)`. Honest input; not auto-extracted from source.
    requires_secrets = ArrayField(models.CharField(max_length=128), default=list, blank=True)

    version = models.PositiveIntegerField(default=1)
    is_latest = models.BooleanField(default=True)

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    deleted = models.BooleanField(default=False)

    class Meta:
        db_table = "agent_custom_tool_template"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name", "version"],
                condition=models.Q(deleted=False),
                name="agent_custom_tool_template_unique_version_per_name",
            ),
            models.UniqueConstraint(
                fields=["team", "name"],
                condition=models.Q(deleted=False, is_latest=True),
                name="agent_custom_tool_template_unique_latest_per_name",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "deleted"]),
            models.Index(fields=["name"]),
        ]

    def __str__(self) -> str:
        return f"{self.name}@v{self.version}"


# ─── Freeze-time join tables ──────────────────────────────────────────
#
# Drafts have no join rows; the spec JSONB is the editable surface.
# At freeze the janitor writes one row per ref inside a single
# `transaction.atomic()`, alongside the bundle copy. The join lets
# the registry's "Used by" panel + "who's on v3?" reports run as
# indexed queries instead of JSONB scans, and prevents a template
# that a frozen revision pins from being hard-deleted.


class AgentRevisionSkillTemplate(UUIDModel):
    """Frozen revision ⇄ skill template binding."""

    revision = models.ForeignKey(
        AgentRevision,
        on_delete=models.CASCADE,
        related_name="skill_template_refs",
    )
    skill_template = models.ForeignKey(
        AgentSkillTemplate,
        # Hard-delete is blocked while any frozen revision references this
        # template — soft delete (`deleted=True`) is the only legal path.
        on_delete=models.PROTECT,
        related_name="revision_refs",
    )
    pinned_version = models.PositiveIntegerField()
    alias = models.CharField(max_length=128)
    ordinal = models.PositiveIntegerField()

    class Meta:
        db_table = "agent_revision_skill_template"
        constraints = [
            models.UniqueConstraint(
                fields=["revision", "alias"],
                name="agent_revision_skill_template_unique_alias",
            ),
        ]
        indexes = [
            models.Index(fields=["skill_template", "pinned_version"]),
        ]


class AgentRevisionCustomToolTemplate(UUIDModel):
    """Frozen revision ⇄ custom tool template binding."""

    revision = models.ForeignKey(
        AgentRevision,
        on_delete=models.CASCADE,
        related_name="custom_tool_template_refs",
    )
    tool_template = models.ForeignKey(
        AgentCustomToolTemplate,
        on_delete=models.PROTECT,
        related_name="revision_refs",
    )
    pinned_version = models.PositiveIntegerField()
    alias = models.CharField(max_length=128)
    ordinal = models.PositiveIntegerField()

    class Meta:
        db_table = "agent_revision_custom_tool_template"
        constraints = [
            models.UniqueConstraint(
                fields=["revision", "alias"],
                name="agent_revision_custom_tool_template_unique_alias",
            ),
        ]
        indexes = [
            models.Index(fields=["tool_template", "pinned_version"]),
        ]


class AgentRevisionNativeTool(UUIDModel):
    """Frozen revision ⇄ native tool id.

    Native tools live in the runner (no DB row to FK against), so this
    table carries the text id directly. Indexed for the same "who uses
    `@posthog/query`?" query the template join enables.
    """

    revision = models.ForeignKey(
        AgentRevision,
        on_delete=models.CASCADE,
        related_name="native_tool_refs",
    )
    native_tool_id = models.CharField(max_length=128)
    ordinal = models.PositiveIntegerField()

    class Meta:
        db_table = "agent_revision_native_tool"
        constraints = [
            models.UniqueConstraint(
                fields=["revision", "native_tool_id"],
                name="agent_revision_native_tool_unique_id",
            ),
        ]
        indexes = [
            models.Index(fields=["native_tool_id"]),
        ]
