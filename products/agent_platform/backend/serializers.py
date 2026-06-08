"""
DRF serializers for the agent_platform authoring API.

Two model serializers (Application, Revision) + a few request-body serializers
for non-CRUD actions (set_env, promote). Bundle-upload + presigned-URL flow is
deferred to the eventual MCP redesign (see TODO B5 in agent-shared).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

import jsonschema
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import AgentApplication, AgentRevision
from .spec_schema import AGENT_SPEC_JSON_SCHEMA, AGENT_SPEC_JSON_SCHEMA_FOR_WRITE


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
            "Computed from `AGENT_INGRESS_PUBLIC_URL` + the agent slug. Null when the deployment has no "
            "public agent-ingress URL configured (e.g. local dev without a tunnel)."
        ),
    )
    slack_interactivity_url = serializers.SerializerMethodField(
        help_text=(
            "Public URL to paste into the Slack app dashboard under Interactivity & Shortcuts → Request URL. "
            "Same source + null behaviour as `slack_events_url`."
        ),
    )

    class Meta:
        model = AgentApplication
        fields = [
            "id",
            "team",
            "name",
            "slug",
            "description",
            "live_revision",
            "archived",
            "archived_at",
            "created_by",
            "created_at",
            "updated_at",
            "slack_events_url",
            "slack_interactivity_url",
        ]
        # encrypted_env is set/cleared via the dedicated `set_env` action;
        # never round-tripped through the standard CRUD payload.
        read_only_fields = [
            "id",
            "team",
            "live_revision",
            "archived_at",
            "created_by",
            "created_at",
            "updated_at",
            "slack_events_url",
            "slack_interactivity_url",
        ]

    @extend_schema_field({"type": "string", "format": "uri", "nullable": True})
    def get_slack_events_url(self, obj: AgentApplication) -> str | None:
        return _slack_path_url(obj.slug, "events")

    @extend_schema_field({"type": "string", "format": "uri", "nullable": True})
    def get_slack_interactivity_url(self, obj: AgentApplication) -> str | None:
        return _slack_path_url(obj.slug, "interactivity")


def _slack_path_url(slug: str, suffix: str) -> str | None:
    base = (settings.AGENT_INGRESS_PUBLIC_URL or "").rstrip("/")
    if not base or not slug:
        return None
    return f"{base}/agents/{slug}/slack/{suffix}"


@extend_schema_field(AGENT_SPEC_JSON_SCHEMA)
class AgentSpecField(serializers.JSONField):
    """Spec JSON typed against `AGENT_SPEC_JSON_SCHEMA` so drf-spectacular
    publishes the real shape downstream — generated TS types, MCP tool
    descriptions, and the OpenAPI doc all see real fields instead of an
    opaque `{}`."""


class AgentRevisionSerializer(serializers.ModelSerializer):
    spec = AgentSpecField(required=False, default=dict)

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
            "created_by",
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


class _SkillFileSerializer(serializers.Serializer):
    path = serializers.CharField(allow_blank=False, trim_whitespace=False)
    content = serializers.CharField(allow_blank=True, trim_whitespace=False)


class WriteSkillRequestSerializer(serializers.Serializer):
    """Body shape for PUT /revisions/<id>/skills/<skill_id>/."""

    description = serializers.CharField(allow_blank=False, trim_whitespace=False)
    body = serializers.CharField(allow_blank=True, trim_whitespace=False)
    files = serializers.ListField(child=_SkillFileSerializer(), required=False, default=list)


class WriteToolRequestSerializer(serializers.Serializer):
    """Body shape for PUT /revisions/<id>/tools/<tool_id>/."""

    description = serializers.CharField(allow_blank=False, trim_whitespace=False)
    args_schema = serializers.DictField(child=serializers.JSONField())
    source = serializers.CharField(allow_blank=False, trim_whitespace=False)


class WriteTypedBundleRequestSerializer(serializers.Serializer):
    """Body shape for PUT /revisions/<id>/bundle/ — the full-replace typed
    payload. See docs/agent-platform/plans/typed-bundle-authoring-api.md §3."""

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
    """Body shape for POST /agent_applications/<id>/approvals/<approval_id>/decide/.

    See docs/agent-platform/plans/approval-gated-tools.md."""

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
