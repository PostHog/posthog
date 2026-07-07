"""
DRF serializers for the agent_platform authoring API.

Two model serializers (Application, Revision) + a few request-body serializers
for non-CRUD actions (set_env, promote). Bundle-upload + presigned-URL flow is
deferred to the eventual MCP redesign (see TODO B5 in agent-shared).
"""

from __future__ import annotations

import json
import string
import secrets
from typing import Any

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import IntegrityError

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.models import User

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


class AgentSpecField(serializers.JSONField):
    """The agent spec JSON. Opaque to OpenAPI on purpose: the authoritative,
    richly-described shape is served live by the `agent-applications-spec-schema`
    tool, emitted from the canonical zod `AgentSpecSchema`. We deliberately do
    not carry a second hand-maintained JSON Schema here just to annotate the
    field — that mirror was the source of the drift this endpoint removed."""

    def to_internal_value(self, data: Any) -> Any:
        # The MCP write tools expose `spec` as an opaque arg, so an authoring
        # model sometimes sends the whole spec as a stringified JSON blob rather
        # than an object. Stored verbatim it's the characters of a string, which
        # the janitor rejects (`invalid_request`). Parse it back to an object so
        # it stores structured; reject a string that isn't a JSON object.
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                raise serializers.ValidationError("spec must be a JSON object, not a string.")
            if not isinstance(data, dict):
                raise serializers.ValidationError("spec must be a JSON object.")
        return super().to_internal_value(data)


# Bound the number of skill references on a revision so freeze (one store fetch +
# one janitor write per ref) can't fan out without limit. Enforced both at
# `set_skill_refs` and again at freeze (refs can reach the column via fork / raw write).
MAX_SKILL_REFS = 50


class SkillRefSerializer(serializers.Serializer):
    """One reference to a versioned skill in the llma-skill store, pinned into
    this agent's bundle at freeze."""

    from_template = serializers.CharField(
        # Mirrors the store's `LLMSkill.name` max_length so an unresolvable,
        # oversized name can't be persisted into the JSON column.
        max_length=64,
        help_text=(
            "Name of the skill in the llma-skill store to pin into this agent. "
            "Resolved at freeze to the chosen `version` and materialized into the bundle."
        ),
    )
    alias = serializers.CharField(
        max_length=64,
        validators=[
            RegexValidator(
                r"^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$",
                message="alias must be lowercase letters, digits, hyphens or underscores, and must start "
                "and end with a letter or digit.",
            )
        ],
        help_text=(
            "Folder the resolved skill is materialized under in the bundle (`skills/<alias>/`). "
            "Lowercase letters, digits, hyphens or underscores, starting and ending with a letter or digit; "
            "must be unique within the revision."
        ),
    )
    version = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Specific published version to pin. Omit to pin the store's latest version at freeze time.",
    )


class SetSkillRefsRequestSerializer(serializers.Serializer):
    """Body for PUT /revisions/<id>/skill_refs/ — full-replace the draft's references."""

    skill_refs = SkillRefSerializer(
        many=True,
        # `many=True` builds a ListSerializer, which accepts max_length to bound the
        # list — drf-stubs types the call against the child and misses the kwarg.
        max_length=MAX_SKILL_REFS,  # type: ignore[call-arg]
        help_text="The complete set of store-skill references for this draft; replaces any existing references.",
    )


class AgentRevisionSerializer(serializers.ModelSerializer):
    spec = AgentSpecField(required=False, default=dict)
    skill_refs = SkillRefSerializer(
        many=True,
        read_only=True,
        help_text=(
            "Store-skill references for this draft, set via the `skill_refs` action and resolved into the "
            "bundle at freeze. Preserved as the authoring record on the frozen revision (and carried forward "
            "when forking a new draft); resolved provenance is stamped onto `spec.skills[].source_version_id`."
        ),
    )
    created_by = serializers.SerializerMethodField(
        help_text="Resolved creator (id, first_name, email) from `created_by_id`, or null if unset or the user was deleted.",
    )

    @extend_schema_field(_CREATED_BY_SCHEMA)
    def get_created_by(self, obj: AgentRevision) -> dict[str, Any] | None:
        return _resolve_created_by(self.context, obj.created_by_id)

    def validate_spec(self, value: Any) -> Any:
        # `skills[]` is server-derived — resolved from `skill_refs` and stamped
        # with provenance at freeze, never author-authored. Pin it to the existing
        # server value (empty on create) so an author spec edit can neither change
        # which skills materialize nor forge `source_version_id` to defeat the
        # freeze legacy guard. `new_draft`/`clone_from` set spec on the model
        # directly (not via this serializer), so a fork's carried skills survive.
        if isinstance(value, dict):
            existing = getattr(self.instance, "spec", None)
            value["skills"] = existing.get("skills", []) if isinstance(existing, dict) else []
        # Structural validation against the spec schema is the janitor's job (the
        # zod `AgentSpecSchema`): the explicit `validate` action, freeze, and the
        # runner all parse against it. There is no Python schema mirror to check
        # here — keeping one in lockstep with zod was the drift this removed. We
        # still enforce the cross-field invariant the serializer owns.
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
            "skill_refs",
            "created_by_id",
            "created_by",
            "created_at",
            "updated_at",
        ]
        # state transitions happen through promote / archive actions; spec is
        # mutable only while state='draft' (enforced in the view). skill_refs is
        # set through the dedicated `skill_refs` action, not this serializer.
        read_only_fields = [
            "id",
            "application",
            "state",
            "bundle_sha256",
            "skill_refs",
            "created_by_id",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            # The runner / janitor address bundles by revision_id; bundle_uri is
            # the storage-prefix metadata. We default it server-side (the view's
            # perform_create fills `fs://<slug>/` when blank) so MCP callers and
            # humans creating a draft don't need to know about it. `allow_blank`
            # is required because the generated MCP tool ships the `default: ""`
            # value explicitly — without it, callers hit "may not be blank".
            "bundle_uri": {
                "required": False,
                "default": "",
                "allow_blank": True,
                "help_text": (
                    "Storage-prefix metadata for the bundle, e.g. `fs://my-agent/`. Optional — leave blank "
                    "and the server fills `fs://<application-slug>/`. Bundles are addressed by revision id "
                    "regardless, so this is only a prefix hint."
                ),
            },
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


class UpdateBundleFileRequestSerializer(serializers.Serializer):
    """Body shape for PUT /revisions/<id>/bundle/file/.

    Edits one `.md` file on a draft revision. `path` is restricted to the
    canonical author surface — `agent.md` or `skills/<id>/SKILL.md` for a
    skill id that already exists in the bundle. Tool source / schema editing
    is out of scope here; use the per-tool endpoint for that.
    """

    path = serializers.CharField(
        allow_blank=False,
        trim_whitespace=False,
        help_text=(
            "Canonical bundle path. Must be `agent.md` or `skills/<id>/SKILL.md` "
            "where `<id>` matches an existing skill in the draft's bundle."
        ),
    )
    content = serializers.CharField(
        allow_blank=True,
        trim_whitespace=False,
        help_text="The new file contents, written verbatim to the bundle store.",
    )


class ImportBundleSkillSerializer(serializers.Serializer):
    """One skill entry in a bulk-import payload.

    The optional `description` is honoured when adding a new skill (or
    overwriting an existing one); when omitted on an existing skill, the
    current description is preserved. Skill `id` must match the canonical
    resource-id regex used by the janitor.
    """

    id = serializers.CharField(
        allow_blank=False,
        trim_whitespace=False,
        help_text="Skill id. Lowercase letters, digits, hyphens, or underscores; must start and end with `[a-z0-9]`.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=False,
        help_text="One-line summary shown in the skill index. Required when adding a new skill; optional when updating one.",
    )
    body = serializers.CharField(
        allow_blank=True,
        trim_whitespace=False,
        help_text="The skill's full markdown body, written to `skills/<id>/SKILL.md`.",
    )


class ImportBundleRequestSerializer(serializers.Serializer):
    """Body shape for POST /revisions/<id>/bundle/import/.

    Bulk-paste hatch for migrating an existing multi-file agent. Either
    `agent_md` or `skills` (or both) may be present. Skills merge by `id`:
    matching ids overwrite their body (and description if provided), new
    ids are appended. Skills NOT mentioned are left alone — the import is
    safe to retry.
    """

    agent_md = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="New `agent.md` contents. When omitted, the existing agent.md is left alone.",
    )
    skills = serializers.ListField(
        child=ImportBundleSkillSerializer(),
        required=False,
        default=list,
        help_text="Per-skill payloads to merge into the bundle by id. When omitted, no skills are touched.",
    )


class WriteSpecRequestSerializer(serializers.Serializer):
    """Body shape for PUT /revisions/<id>/spec/. The body's `spec` object
    is the author-facing slice (skills/tools are server-derived at freeze)."""

    spec = serializers.DictField(child=serializers.JSONField())


class WriteToolRequestSerializer(serializers.Serializer):
    """Body shape for PUT /revisions/<id>/tools/<tool_id>/."""

    description = serializers.CharField(allow_blank=False, trim_whitespace=False)
    args_schema = serializers.DictField(child=serializers.JSONField())
    source = serializers.CharField(allow_blank=False, trim_whitespace=False)  # type: ignore[assignment]  # field named `source` shadows DRF Field.source


class DryRunToolRequestSerializer(serializers.Serializer):
    """Body shape for POST /revisions/<id>/tools/<tool_id>/dry_run/.

    Executes the persisted compiled.js once in the janitor's single-shot
    sandbox with caller-supplied args + a stubbed ctx. No real secrets
    leave Django — `mock_secrets` is a `{name → opaque nonce}` map the
    sandbox plumbs into `ctx.secrets.ref(name)` so the tool body returns
    something deterministic to the author."""

    args = serializers.JSONField(
        help_text="Synthetic args the tool's `actions.default` is called with. Free-form JSON; the sandbox doesn't validate against the tool's `args_schema` — that's the author's responsibility to keep in sync."
    )
    mock_secrets = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        required=False,
        help_text="Optional `{secret_name → placeholder_string}` map. The string is returned verbatim by `ctx.secrets.ref(name)` inside the tool. The real secret value never enters the sandbox.",
    )


class WriteTypedBundleRequestSerializer(serializers.Serializer):
    """Body shape for PUT /revisions/<id>/bundle/ — the full-replace typed
    payload. Skills are not authored here: they come from the llma-skill store
    via `skill_refs` and are materialized into the bundle at freeze."""

    agent_md = serializers.CharField(allow_blank=True, trim_whitespace=False)
    tools = serializers.ListField(child=WriteToolRequestSerializer(), required=False, default=list)
    spec = serializers.DictField(child=serializers.JSONField())

    def to_internal_value(self, data: dict) -> dict:
        """Tool items carry an `id` field that the nested serializer doesn't
        declare (it lives in the URL for the single-resource PUTs). Stash +
        restore so the per-item validation still passes."""
        tools = data.get("tools", [])
        tool_ids = [t.get("id") for t in tools]
        stripped = {
            **data,
            "tools": [{k: v for k, v in t.items() if k != "id"} for t in tools],
        }
        out = super().to_internal_value(stripped)
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


class PreviewProxyInvokeRequestSerializer(serializers.Serializer):
    """Body forwarded verbatim to the agent ingress for a *preview* invoke of a
    non-live revision. The meaningful shape depends on the `rest` path segment:

    - `run` — `{ message }`: the user message that starts a new session.
    - `send` — `{ session_id, message }`: append a message to a running session.
    - `cancel` / `listen` — no body.

    Documents `message` / `session_id` so the generated MCP tool exposes them;
    any extra keys are still forwarded as-is to ingress.
    """

    message = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="User message to deliver to the agent. Required for `run` (starts the session) and `send` (appends to it); ignored for `cancel` / `listen`.",
    )
    session_id = serializers.CharField(
        required=False,
        help_text="Target session id for `send` — the running session to append the message to. Omit for `run` (a fresh session is created).",
    )
