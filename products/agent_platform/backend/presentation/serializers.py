"""
DRF serializers for the agent_platform authoring API.

Two model serializers (Application, Revision) + a few request-body serializers
for non-CRUD actions (set_env, promote). Bundle-upload + presigned-URL flow is
deferred to the eventual MCP redesign (see TODO B5 in agent-shared).
"""

from __future__ import annotations

import string
import secrets
from typing import Any

from django.conf import settings
from django.db import IntegrityError

import jsonschema
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.models import User

from ..logic.spec_schema import AGENT_SPEC_JSON_SCHEMA, AGENT_SPEC_JSON_SCHEMA_FOR_WRITE
from ..models import AgentApplication, AgentRevision

# Opaque random slug: leading letter (DNS-label-safe) + lowercase alphanumerics.
# No dashes, so it can't be misread as the `<slug>-<revHex>` revision form, and
# no name prefix — human-readable slugs are reserved for the explicit allowlist.
_SLUG_ALPHABET = string.ascii_lowercase + string.digits
_SLUG_LENGTH = 12


def _mint_unique_slug() -> str:
    """Mint a globally-unique opaque slug. The global partial unique index on
    `slug` is the final guard; this pre-check keeps the common path off the
    IntegrityError retry."""
    for _ in range(10):
        candidate = secrets.choice(string.ascii_lowercase) + "".join(
            secrets.choice(_SLUG_ALPHABET) for _ in range(_SLUG_LENGTH - 1)
        )
        if not AgentApplication.all_teams.filter(slug=candidate, archived=False).exists():
            return candidate
    raise serializers.ValidationError("could not generate a unique slug; retry")


# Shape of the resolved `created_by` object — exactly the fields the agent
# console renders. Nullable: `created_by_id` may be unset (system rows) or
# point at a since-deleted user.
_CREATED_BY_SCHEMA = {
    "type": "object",
    "nullable": True,
    "properties": {
        "id": {"type": "integer"},
        "first_name": {"type": "string"},
        "email": {"type": "string", "format": "email"},
    },
}


def _resolve_created_by(context: dict[str, Any], user_id: int | None) -> dict[str, Any] | None:
    """Resolve a `created_by_id` (plain int — these are product-DB models with
    no cross-DB FK to User) into a minimal user object. Cached per serializer
    context so a list endpoint resolves each distinct user once."""
    if not user_id:
        return None
    cache: dict[int, dict[str, Any] | None] = context.setdefault("_created_by_cache", {})
    if user_id not in cache:
        user = User.objects.filter(pk=user_id).only("id", "first_name", "email").first()
        cache[user_id] = (
            {"id": user.id, "first_name": user.first_name, "email": user.email} if user is not None else None
        )
    return cache[user_id]


def _validate_mcp_tool_names_unique(spec: Any) -> None:
    # JSON Schema's `uniqueItems` only compares whole-value equality, so it
    # can't catch a bare string colliding with an object of the same `name`
    # in `mcps[].external.tools[]`. Mirror the zod `.refine()` (same message)
    # so the API rejects duplicates here instead of letting the runner blow up
    # with a confusing Zod error at session open.
    if not isinstance(spec, dict):
        return
    mcps = spec.get("mcps")
    if not isinstance(mcps, list):
        return
    for i, mcp in enumerate(mcps):
        if not isinstance(mcp, dict):
            continue
        tools = mcp.get("tools")
        if not isinstance(tools, list):
            continue
        seen: set[str] = set()
        for entry in tools:
            name = entry if isinstance(entry, str) else entry.get("name") if isinstance(entry, dict) else None
            if not isinstance(name, str):
                continue
            if name in seen:
                raise serializers.ValidationError(f"spec.mcps.{i}.tools: mcps[].tools[] entries must have unique names")
            seen.add(name)


class AgentApplicationSerializer(serializers.ModelSerializer):
    slack_events_url = serializers.SerializerMethodField(
        help_text=(
            "Public URL to paste into the Slack app dashboard under Event Subscriptions → Request URL. "
            "Computed from the agent slug and the deployment's ingress routing mode "
            "(`AGENT_INGRESS_DOMAIN_SUFFIX` in domain mode, `AGENT_INGRESS_PUBLIC_URL` in path mode). "
            "Null when no public agent-ingress URL is configured (e.g. local dev without a tunnel)."
        ),
    )
    slack_interactivity_url = serializers.SerializerMethodField(
        help_text=(
            "Public URL to paste into the Slack app dashboard under Interactivity & Shortcuts → Request URL. "
            "Same source + null behaviour as `slack_events_url`."
        ),
    )
    ingress_base_url = serializers.SerializerMethodField(
        help_text=(
            "Mode-aware base URL the agent's trigger routes hang off — append `/webhook`, `/run`, `/mcp`, etc. "
            "Domain mode: `https://<slug><suffix>`; path mode: `<public_url>/agents/<slug>`. Same source + null "
            "behaviour as `slack_events_url` (null when no public ingress URL is configured)."
        ),
    )
    created_by = serializers.SerializerMethodField(
        help_text="Resolved creator (id, first_name, email) from `created_by_id`, or null if unset or the user was deleted.",
    )
    # Optional on write: the server mints a globally-unique opaque slug unless
    # the team is on AGENT_PLATFORM_EXPLICIT_SLUG_TEAM_IDS and supplies one.
    # Always present on read.
    slug = serializers.SlugField(
        max_length=63,
        required=False,
        help_text=(
            "Globally-unique URL identifier. Server-minted as an opaque random slug on create; "
            "only allowlisted first-party teams may set it explicitly. Slugs live in one "
            "global namespace (domain-mode ingress routing carries no team)."
        ),
    )

    class Meta:
        model = AgentApplication
        fields = [
            "id",
            "team_id",
            "name",
            "slug",
            "description",
            "live_revision",
            "archived",
            "archived_at",
            "created_by_id",
            "created_by",
            "created_at",
            "updated_at",
            "slack_events_url",
            "slack_interactivity_url",
            "ingress_base_url",
        ]
        # encrypted_env is set/cleared via the dedicated `set_env` action;
        # never round-tripped through the standard CRUD payload.
        read_only_fields = [
            "id",
            "team_id",
            "live_revision",
            "archived_at",
            "created_by_id",
            "created_at",
            "updated_at",
            "slack_events_url",
            "slack_interactivity_url",
            "ingress_base_url",
        ]

    @extend_schema_field(_CREATED_BY_SCHEMA)
    def get_created_by(self, obj: AgentApplication) -> dict[str, Any] | None:
        return _resolve_created_by(self.context, obj.created_by_id)

    @extend_schema_field({"type": "string", "format": "uri", "nullable": True})
    def get_slack_events_url(self, obj: AgentApplication) -> str | None:
        return _slack_path_url(obj.slug, "events")

    @extend_schema_field({"type": "string", "format": "uri", "nullable": True})
    def get_slack_interactivity_url(self, obj: AgentApplication) -> str | None:
        return _slack_path_url(obj.slug, "interactivity")

    @extend_schema_field({"type": "string", "format": "uri", "nullable": True})
    def get_ingress_base_url(self, obj: AgentApplication) -> str | None:
        # Empty path → the base the routes hang off (`…/agents/<slug>` in path
        # mode, `https://<slug><suffix>` in domain mode).
        return agent_ingress_route_url(obj.slug, "")

    def _explicit_slug_allowed(self, team_id: int | None) -> bool:
        return team_id is not None and team_id in settings.AGENT_PLATFORM_EXPLICIT_SLUG_TEAM_IDS

    def create(self, validated_data: dict[str, Any]) -> AgentApplication:
        team_id = validated_data.get("team_id")
        explicit_slug = validated_data.pop("slug", None)
        if explicit_slug and self._explicit_slug_allowed(team_id):
            validated_data["slug"] = explicit_slug
        else:
            validated_data["slug"] = _mint_unique_slug()
        try:
            return super().create(validated_data)
        except IntegrityError as e:
            raise serializers.ValidationError({"slug": "An agent with this slug already exists."}) from e

    def update(self, instance: AgentApplication, validated_data: dict[str, Any]) -> AgentApplication:
        # Slug is immutable except for allowlisted teams — renaming it would
        # break the live agent's routing URLs. Drop any other team's attempt.
        explicit_slug = validated_data.pop("slug", None)
        if explicit_slug and explicit_slug != instance.slug and self._explicit_slug_allowed(instance.team_id):
            validated_data["slug"] = explicit_slug
        try:
            return super().update(instance, validated_data)
        except IntegrityError as e:
            raise serializers.ValidationError({"slug": "An agent with this slug already exists."}) from e


def agent_ingress_route_url(slug: str, path: str) -> str | None:
    """Absolute URL of an agent's ingress route, matching what the deployed
    ingress actually serves. Mode mirrors `AGENT_INGRESS_ROUTING_MODE` (and the
    ingress's own `ROUTING_MODE`):

      domain → ``https://<slug><suffix><path>``    (slug in host, routes at root)
      path   → ``<public_url>/agents/<slug><path>`` (slug in path)

    `path` is the leading-slash route (e.g. `/slack/events`). Returns None when
    the active mode's required setting is unset or `slug` is empty — the caller
    omits the field, signalling "not externally reachable".
    """
    if not slug:
        return None
    if settings.AGENT_INGRESS_ROUTING_MODE == "domain":
        suffix = (settings.AGENT_INGRESS_DOMAIN_SUFFIX or "").strip()
        return f"https://{slug}{suffix}{path}" if suffix else None
    base = (settings.AGENT_INGRESS_PUBLIC_URL or "").rstrip("/")
    return f"{base}/agents/{slug}{path}" if base else None


def _slack_path_url(slug: str, suffix: str) -> str | None:
    return agent_ingress_route_url(slug, f"/slack/{suffix}")


@extend_schema_field(AGENT_SPEC_JSON_SCHEMA)
class AgentSpecField(serializers.JSONField):
    """Spec JSON typed against `AGENT_SPEC_JSON_SCHEMA` so drf-spectacular
    publishes the real shape downstream — generated TS types, MCP tool
    descriptions, and the OpenAPI doc all see real fields instead of an
    opaque `{}`."""


class AgentRevisionSerializer(serializers.ModelSerializer):
    spec = AgentSpecField(required=False, default=dict)
    created_by = serializers.SerializerMethodField(
        help_text="Resolved creator (id, first_name, email) from `created_by_id`, or null if unset or the user was deleted.",
    )

    @extend_schema_field(_CREATED_BY_SCHEMA)
    def get_created_by(self, obj: AgentRevision) -> dict[str, Any] | None:
        return _resolve_created_by(self.context, obj.created_by_id)

    def validate_spec(self, value: Any) -> Any:
        # Same shape the janitor's `AgentSpecSchema.parse` will reject on
        # read. Catching it here turns a future 500 / process-level surprise
        # into a clean 400 at write time.
        try:
            jsonschema.validate(value, AGENT_SPEC_JSON_SCHEMA_FOR_WRITE)
        except jsonschema.ValidationError as e:
            path = ".".join(str(p) for p in e.absolute_path) or "<root>"
            raise serializers.ValidationError(f"spec.{path}: {e.message}") from e
        _validate_mcp_tool_names_unique(value)
        return value

    class Meta:
        model = AgentRevision
        fields = [
            "id",
            "application",
            "parent_revision",
            "state",
            "bundle_uri",
            "bundle_sha256",
            "spec",
            "created_by_id",
            "created_by",
            "created_at",
            "updated_at",
        ]
        # state transitions happen through promote / archive actions; spec is
        # mutable only while state='draft' (enforced in the view).
        read_only_fields = [
            "id",
            "application",
            "state",
            "bundle_sha256",
            "created_by_id",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            # The runner / janitor address bundles by revision_id; bundle_uri is
            # the storage-prefix metadata. We default it server-side so MCP
            # callers (and humans) creating a draft don't need to know about it.
            "bundle_uri": {"required": False, "default": ""},
        }


class SetEnvRequestSerializer(serializers.Serializer):
    """Body shape for AgentApplicationViewSet.set_env.

    `env` is a JSON object of string→string. The view encrypts it via the
    same Fernet schedule the worker uses to decrypt.
    """

    env = serializers.DictField(child=serializers.CharField(allow_blank=True), allow_empty=True)


class SetEnvKeyRequestSerializer(serializers.Serializer):
    """Body shape for AgentApplicationViewSet.env_keys_set — single secret upsert.

    The view merges `{KEY: value}` into the existing encrypted env block
    without touching other keys, so callers can set or rotate one secret
    without needing to read the whole block back.
    """

    value = serializers.CharField(allow_blank=True, trim_whitespace=False)


class PreviewTokenMintRequestSerializer(serializers.Serializer):
    """Body shape for `POST .../preview-token/`.

    `secret_override` is optional per-session secret overlay applied at preview
    mint time. Keys MUST be a subset of `revision.spec["secrets"]` — the view
    validates server-side and rejects undeclared keys with a field-level
    400. The overlay is encrypted into the minted JWT's claims (the JWT is
    HS256-signed with `AGENT_INTERNAL_SIGNING_KEY` so the override is
    tamper-proof in transit); the ingress extracts it at session create and
    stamps it onto the row. It is never returned through any read path and
    never persisted as plaintext.

    Values are bounded at the DRF level (CharField default ~1 KiB) and the
    total serialized map is capped by the view so the JWT stays under typical
    header limits. Authors who need to test against a real secret value should
    set it through the standard `env_keys` UI instead of this hatch.
    """

    secret_override = serializers.DictField(
        child=serializers.CharField(allow_blank=True, trim_whitespace=False, max_length=4096),
        required=False,
        allow_empty=True,
        help_text=(
            "Per-session secret overlay applied for the resulting preview session. Keys must be declared in "
            "`spec.secrets[]`; undeclared keys are rejected with a 400. Values are encrypted into the JWT and "
            "applied only for the lifetime of one session — never persisted to `encrypted_env`. Omit to inherit "
            "live secrets unchanged."
        ),
    )


class PromoteRevisionRequestSerializer(serializers.Serializer):
    """Body shape for AgentRevisionViewSet.promote.

    Empty today — promote takes the calling revision's id from the URL and
    flips it `ready → live`, updating the parent application's
    `live_revision`. Left as a body-bearing endpoint so we can add fields
    later (rollback target, audit comment) without changing the URL shape.
    """


class WriteAgentMdRequestSerializer(serializers.Serializer):
    """Body shape for PUT /revisions/<id>/agent_md/."""

    content = serializers.CharField(allow_blank=True, trim_whitespace=False)


class WriteSpecRequestSerializer(serializers.Serializer):
    """Body shape for PUT /revisions/<id>/spec/. The body's `spec` object
    is the author-facing slice (skills/tools are server-derived at freeze)."""

    spec = serializers.DictField(child=serializers.JSONField())


class WriteSkillRequestSerializer(serializers.Serializer):
    """Body shape for PUT /revisions/<id>/skills/<skill_id>/. The body is stored
    at the canonical `skills/<skill_id>/SKILL.md` path in the bundle."""

    description = serializers.CharField(
        allow_blank=False,
        trim_whitespace=False,
        help_text="One-line summary shown in the skill index; the model uses it to decide when to load the skill.",
    )
    body = serializers.CharField(
        allow_blank=True,
        trim_whitespace=False,
        help_text="The skill's full markdown body, stored at `skills/<skill_id>/SKILL.md`.",
    )


class WriteToolRequestSerializer(serializers.Serializer):
    """Body shape for PUT /revisions/<id>/tools/<tool_id>/."""

    description = serializers.CharField(allow_blank=False, trim_whitespace=False)
    args_schema = serializers.DictField(child=serializers.JSONField())
    source = serializers.CharField(allow_blank=False, trim_whitespace=False)  # type: ignore[assignment]  # field named `source` shadows DRF Field.source


class WriteTypedBundleRequestSerializer(serializers.Serializer):
    """Body shape for PUT /revisions/<id>/bundle/ — the full-replace typed
    payload."""

    agent_md = serializers.CharField(allow_blank=True, trim_whitespace=False)
    skills = serializers.ListField(child=WriteSkillRequestSerializer(), required=False, default=list)
    tools = serializers.ListField(child=WriteToolRequestSerializer(), required=False, default=list)
    spec = serializers.DictField(child=serializers.JSONField())

    def to_internal_value(self, data: dict) -> dict:
        """Skill / tool items carry an `id` field that the nested serializer
        doesn't declare (it lives in the URL for the single-resource PUTs).
        Stash + restore so the per-item validation still passes."""
        skills = data.get("skills", [])
        tools = data.get("tools", [])
        skill_ids = [s.get("id") for s in skills]
        tool_ids = [t.get("id") for t in tools]
        # Strip ids so the inner serializers don't complain about unknowns.
        stripped = {
            **data,
            "skills": [{k: v for k, v in s.items() if k != "id"} for s in skills],
            "tools": [{k: v for k, v in t.items() if k != "id"} for t in tools],
        }
        out = super().to_internal_value(stripped)
        # Reattach ids — janitor wants them.
        out["skills"] = [{**s, "id": skill_ids[i]} for i, s in enumerate(out.get("skills", []))]
        out["tools"] = [{**t, "id": tool_ids[i]} for i, t in enumerate(out.get("tools", []))]
        return out


class CloneFromRequestSerializer(serializers.Serializer):
    """Body shape for POST /revisions/<id>/clone_from/ — copy every file
    from `source_revision_id` into this (draft) revision."""

    source_revision_id = serializers.UUIDField()


class NewDraftRevisionRequestSerializer(serializers.Serializer):
    """Body shape for POST /revisions/clone_from/ — atomically create a new
    draft revision under `application_id` and clone its initial bundle from
    `source_revision_id`. Convenience for the "edit live" flow so the MCP
    doesn't have to do create-then-clone-from in two calls."""

    application_id = serializers.UUIDField()
    source_revision_id = serializers.UUIDField()


class DecideApprovalRequestSerializer(serializers.Serializer):
    """Body shape for POST /agent_applications/<id>/approvals/<approval_id>/decide/."""

    decision = serializers.ChoiceField(
        choices=["approve", "reject"],
        help_text="The approver's decision. `approve` runs the tool platform-side with the (possibly edited) args; `reject` records a terminal rejection and wakes the session with a synthetic rejected tool_result.",
    )
    edited_args = serializers.DictField(
        child=serializers.JSONField(),
        required=False,
        help_text="Approver-edited tool arguments. Only honoured when the tool's `approval_policy.allow_edit` is `true`; otherwise the janitor returns 422.",
    )
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Free-form approver note. Surfaces in the session's synthetic tool_result so the model can communicate the reason back to the user.",
    )
