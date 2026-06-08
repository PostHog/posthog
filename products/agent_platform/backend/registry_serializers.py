"""
DRF serializers for the Tools & Skills registry.

Two parallel families — one for `AgentSkillTemplate` (markdown +
companion files), one for `AgentCustomToolTemplate` (TypeScript
source + args schema). Shared shape: summary / detail / publish /
duplicate / edit / file ops.

Every field carries `help_text` so the OpenAPI generator (and the MCP
codegen that consumes it) ship richer docs for free.
"""

from __future__ import annotations

import re
from typing import Any

from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer

from .models import (
    AgentCustomToolTemplate,
    AgentRevisionCustomToolTemplate,
    AgentRevisionSkillTemplate,
    AgentSkillTemplate,
    AgentSkillTemplateFile,
)
from .skill_frontmatter import (
    COMPATIBILITY_MAX,
    DESCRIPTION_MAX,
    NAME_MAX,
    SkillSpecError,
    validate_allowed_tools,
    validate_compatibility,
    validate_description,
    validate_metadata_map,
)


def _spec(fn: Any, value: Any) -> Any:
    """Run an Agent Skills spec validator, surfacing failures as DRF errors."""
    try:
        return fn(value)
    except SkillSpecError as exc:
        raise serializers.ValidationError(exc.message, code="spec")


# Slug rules — lowercase a-z + digits + hyphen; no leading/trailing hyphen;
# no consecutive hyphens. Mirrors the LLMSkill validation so the registry
# UI's input affordances are consistent with the ai_observability product.
SKILL_NAME_REGEX = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
# Canonical PostHog-owned templates use the `@posthog/` prefix.
CANONICAL_NAME_REGEX = re.compile(r"^@posthog/[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")

MAX_BODY_BYTES = 1_000_000
MAX_FILE_BYTES = 1_000_000
MAX_FILE_COUNT = 50
MAX_SOURCE_BYTES = 1_000_000

RESERVED_NAMES = {"new"}


def _validate_template_name(value: str) -> str:
    """Shared name validator: applies to both skill + custom-tool templates.

    Accepts plain slugs or canonical `@posthog/<slug>` names. The viewset
    enforces "team members can't create `@posthog/` names" — that gate
    lives at the call site because it needs the request user.
    """
    if not value:
        raise serializers.ValidationError("Name is required.", code="required")
    if value.lower() in RESERVED_NAMES:
        raise serializers.ValidationError(f"'{value}' is reserved and cannot be used.", code="reserved_name")
    if value.startswith("@posthog/"):
        if not CANONICAL_NAME_REGEX.match(value):
            raise serializers.ValidationError(
                "Canonical names must match '@posthog/<lowercase slug>'.",
                code="invalid_name",
            )
        return value
    if not SKILL_NAME_REGEX.match(value):
        raise serializers.ValidationError(
            "Names must be lowercase letters, digits, and hyphens. No leading / trailing hyphen.",
            code="invalid_name",
        )
    if "--" in value:
        raise serializers.ValidationError("Consecutive hyphens are not allowed.", code="invalid_name")
    return value


def _validate_file_path(value: str) -> str:
    """Path rules for companion files: relative, no traversal."""
    normalized = value.replace("\\", "/")
    if normalized.startswith("/"):
        raise serializers.ValidationError("Paths must be relative.")
    parts = normalized.split("/")
    if any(part == ".." for part in parts):
        raise serializers.ValidationError("Paths must not contain '..' traversal segments.")
    if any(part == "" for part in parts):
        raise serializers.ValidationError("Paths must not contain empty segments.")
    return value


def _validate_body_size(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_BODY_BYTES:
        raise serializers.ValidationError(f"Body exceeds the {MAX_BODY_BYTES}-byte limit.", code="max_size")
    return value


def _validate_source_size(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise serializers.ValidationError(f"Source exceeds the {MAX_SOURCE_BYTES}-byte limit.", code="max_size")
    return value


# ───────────────────────────── Skill templates ──────────────────────────────


class SkillTemplateFileSerializer(serializers.ModelSerializer):
    path = serializers.CharField(
        max_length=512,
        help_text="Relative path inside the skill folder; may include subfolders (e.g. `references/api.md`, `scripts/run.py`, `assets/x/y.json`). Becomes `bundle/skills/<alias>/<path>` at freeze. No `..` traversal or absolute paths.",
    )
    content = serializers.CharField(
        allow_blank=True,
        help_text="File body. Plain text or markdown — companion files are not interpreted by the runner.",
    )
    content_type = serializers.CharField(
        max_length=128,
        default="text/plain",
        help_text="MIME type hint. Read-only at runtime; aids the registry UI's file viewer.",
    )

    class Meta:
        model = AgentSkillTemplateFile
        fields = ("id", "path", "content", "content_type")
        read_only_fields = ("id",)

    def validate_path(self, value: str) -> str:
        return _validate_file_path(value)


class SkillTemplateSummarySerializer(serializers.ModelSerializer):
    """List shape — no body / file contents (keeps the index page fast)."""

    file_count = serializers.SerializerMethodField(
        help_text="Number of companion files attached to the current version."
    )
    usage_count = serializers.SerializerMethodField(
        help_text="Number of frozen agent revisions pinning this template (any version)."
    )
    created_by = UserBasicSerializer(read_only=True, help_text="Publisher. Null for canonical PostHog-owned templates.")
    license = serializers.CharField(
        help_text="Agent Skills `license` frontmatter — license name or a reference to a bundled license file. Blank if unset."
    )
    compatibility = serializers.CharField(
        help_text="Agent Skills `compatibility` frontmatter — environment requirements (intended product, packages, network). Blank if unset."
    )

    class Meta:
        model = AgentSkillTemplate
        # Widened to tuple[str, ...] so subclasses (e.g. SkillTemplateDetailSerializer)
        # can extend without tripping the Liskov check on the inferred fixed-size tuple.
        fields: tuple[str, ...] = (
            "id",
            "name",
            "description",
            "version",
            "is_latest",
            "file_count",
            "usage_count",
            "license",
            "compatibility",
            "metadata",
            "allowed_tools",
            "created_by",
            "updated_at",
        )
        read_only_fields = fields

    def get_file_count(self, obj: AgentSkillTemplate) -> int:
        # Treat the index `body` as a logical "SKILL.md" file for the count.
        return 1 + obj.files.count()

    def get_usage_count(self, obj: AgentSkillTemplate) -> int:
        return AgentRevisionSkillTemplate.objects.filter(skill_template__name=obj.name).count()


class SkillTemplateDetailSerializer(SkillTemplateSummarySerializer):
    """Detail shape: adds body + files. Used by the registry detail page."""

    body = serializers.CharField(allow_blank=True, help_text="Markdown body. The `SKILL.md` equivalent.")
    files = SkillTemplateFileSerializer(
        many=True, read_only=True, help_text="Companion files attached to this version."
    )

    class Meta(SkillTemplateSummarySerializer.Meta):
        fields = (*SkillTemplateSummarySerializer.Meta.fields, "body", "files")
        read_only_fields = fields


class SkillTemplateCreateSerializer(serializers.Serializer):
    """Initial-create payload — produces v1."""

    name = serializers.CharField(
        max_length=NAME_MAX,
        help_text="Slug-shaped name unique per team (max 64 chars, per the Agent Skills spec). `@posthog/<slug>` is reserved for canonical templates.",
    )
    description = serializers.CharField(
        max_length=DESCRIPTION_MAX,
        help_text="Required description (1–1024 chars, per the Agent Skills spec) — what the skill does and when to use it. Shown in the list view + system-prompt skill index.",
    )
    body = serializers.CharField(
        allow_blank=True,
        required=False,
        default="",
        help_text="Initial SKILL.md markdown body. Any leading YAML frontmatter is stripped at freeze — frontmatter is assembled from the structured fields.",
    )
    license = serializers.CharField(
        max_length=256,
        required=False,
        allow_blank=True,
        default="",
        help_text="Agent Skills `license` frontmatter — license name or a reference to a bundled license file.",
    )
    compatibility = serializers.CharField(
        max_length=COMPATIBILITY_MAX,
        required=False,
        allow_blank=True,
        default="",
        help_text="Agent Skills `compatibility` frontmatter — environment requirements (intended product, packages, network access). Max 500 chars.",
    )
    files = serializers.ListField(
        child=SkillTemplateFileSerializer(),
        required=False,
        default=list,
        help_text="Optional companion files (scripts/, references/, assets/ — arbitrarily nested) at creation time.",
    )
    metadata = serializers.JSONField(
        required=False,
        default=dict,
        help_text="Agent Skills `metadata` map (string → string) for non-promoted keys like author or version.",
    )
    # DRF stub types `default` as Mapping; runtime accepts any JSON-serialisable callable.
    allowed_tools = serializers.JSONField(
        required=False,
        default=list,  # type: ignore[arg-type]
        help_text="Optional list of tool ids the skill expects to reach for. Emitted as the spec's space-separated `allowed-tools` frontmatter at freeze.",
    )

    def validate_name(self, value: str) -> str:
        return _validate_template_name(value)

    def validate_description(self, value: str) -> str:
        return _spec(validate_description, value)

    def validate_compatibility(self, value: str) -> str:
        return _spec(validate_compatibility, value)

    def validate_metadata(self, value: Any) -> dict[str, str]:
        return _spec(validate_metadata_map, value)

    def validate_allowed_tools(self, value: Any) -> list[str]:
        return _spec(validate_allowed_tools, value)

    def validate_body(self, value: str) -> str:
        return _validate_body_size(value)

    def validate_files(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(value) > MAX_FILE_COUNT:
            raise serializers.ValidationError(f"At most {MAX_FILE_COUNT} files per skill.", code="max_count")
        paths = [f["path"] for f in value]
        if len(paths) != len(set(paths)):
            raise serializers.ValidationError("Duplicate file paths are not allowed.")
        for f in value:
            if len(f["content"].encode("utf-8")) > MAX_FILE_BYTES:
                raise serializers.ValidationError(f"File {f['path']!r} exceeds the {MAX_FILE_BYTES}-byte limit.")
        return value


class SkillTemplateEditSerializer(serializers.Serializer):
    """A single find/replace edit applied to body or a file's content."""

    old = serializers.CharField(allow_blank=False, help_text="Text to locate (must match exactly once).")
    new = serializers.CharField(allow_blank=True, help_text="Replacement text.")
    file_path = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Apply this edit to a companion file instead of the body. Null/omitted = body edit.",
    )


class SkillTemplatePublishSerializer(serializers.Serializer):
    """Publish a new version.

    Supply EITHER `body` (full overwrite) OR `edits` (structured
    find/replace). The viewset rejects requests carrying both.
    """

    description = serializers.CharField(
        max_length=DESCRIPTION_MAX,
        required=False,
        help_text="Overrides the prior description (1–1024 chars, non-empty). Omit to keep the prior value.",
    )
    body = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Full new body. Mutually exclusive with `edits`.",
    )
    edits = serializers.ListField(
        child=SkillTemplateEditSerializer(),
        required=False,
        help_text="Structured edits. Each `old` must match exactly once in the current body / file.",
    )
    license = serializers.CharField(
        max_length=256,
        required=False,
        allow_blank=True,
        help_text="Overrides the `license` frontmatter. Omit to keep the prior value.",
    )
    compatibility = serializers.CharField(
        max_length=COMPATIBILITY_MAX,
        required=False,
        allow_blank=True,
        help_text="Overrides the `compatibility` frontmatter (max 500 chars). Omit to keep the prior value.",
    )
    metadata = serializers.JSONField(
        required=False, help_text="Overrides the metadata map. Omit to keep the prior value."
    )
    allowed_tools = serializers.JSONField(
        required=False,
        help_text="Overrides allowed_tools. Omit to keep the prior value.",
    )

    def validate_description(self, value: str) -> str:
        return _spec(validate_description, value)

    def validate_compatibility(self, value: str) -> str:
        return _spec(validate_compatibility, value)

    def validate_metadata(self, value: Any) -> dict[str, str]:
        return _spec(validate_metadata_map, value)

    def validate_allowed_tools(self, value: Any) -> list[str]:
        return _spec(validate_allowed_tools, value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        body_given = "body" in attrs
        edits_given = "edits" in attrs and attrs["edits"]
        if body_given and edits_given:
            raise serializers.ValidationError("Provide either `body` or `edits`, not both.")
        if "body" in attrs:
            _validate_body_size(attrs["body"])
        return attrs


class SkillTemplateDuplicateSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=NAME_MAX,
        help_text="Slug for the new duplicate (max 64 chars). Must not collide with an existing template.",
    )
    description = serializers.CharField(
        max_length=DESCRIPTION_MAX,
        required=False,
        help_text="Description for the new template (1–1024 chars, non-empty). Omit to keep the source's description.",
    )

    def validate_name(self, value: str) -> str:
        return _validate_template_name(value)

    def validate_description(self, value: str) -> str:
        # Match create/publish: an explicit description must satisfy the spec
        # (non-empty). Omitting it falls back to the source's description.
        return _spec(validate_description, value)


class SkillTemplateFileWriteSerializer(serializers.Serializer):
    path = serializers.CharField(
        max_length=512,
        help_text="Relative path inside the skill folder; may include subfolders (e.g. `references/api.md`, `scripts/run.py`). No `..` traversal or absolute paths.",
    )
    content = serializers.CharField(allow_blank=True, help_text="File body.")
    content_type = serializers.CharField(
        max_length=128,
        required=False,
        default="text/plain",
        help_text="MIME type hint.",
    )

    def validate_path(self, value: str) -> str:
        return _validate_file_path(value)

    def validate_content(self, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_FILE_BYTES:
            raise serializers.ValidationError(f"File exceeds the {MAX_FILE_BYTES}-byte limit.")
        return value


class SkillTemplateFileRenameSerializer(serializers.Serializer):
    from_path = serializers.CharField(
        max_length=512, help_text="Existing file path inside the skill folder (subfolders allowed)."
    )
    to_path = serializers.CharField(
        max_length=512,
        help_text="New path (subfolders allowed); may move the file between subfolders. Must not collide with another file.",
    )

    def validate_from_path(self, value: str) -> str:
        return _validate_file_path(value)

    def validate_to_path(self, value: str) -> str:
        return _validate_file_path(value)


class SkillTemplateUsageSerializer(serializers.Serializer):
    """Read shape returned by `…/usages/`. Sourced from the join table."""

    agent_slug = serializers.CharField(help_text="Slug of the agent whose revision pins this template.")
    agent_name = serializers.CharField(help_text="Display name of the agent.")
    revision_id = serializers.UUIDField(help_text="Frozen revision id.")
    revision_short_id = serializers.CharField(help_text="First 8 chars of the revision id, for display.")
    pinned_version = serializers.IntegerField(help_text="Template version pinned at freeze.")


# ─────────────────────────── Custom tool templates ──────────────────────────


class CustomToolTemplateSummarySerializer(serializers.ModelSerializer):
    usage_count = serializers.SerializerMethodField(
        help_text="Number of frozen agent revisions pinning this template (any version)."
    )
    created_by = UserBasicSerializer(read_only=True, help_text="Publisher. Null for canonical PostHog-owned templates.")

    class Meta:
        model = AgentCustomToolTemplate
        # Widened to tuple[str, ...] so subclasses (e.g. CustomToolTemplateDetailSerializer)
        # can extend without tripping the Liskov check on the inferred fixed-size tuple.
        fields: tuple[str, ...] = (
            "id",
            "name",
            "description",
            "version",
            "is_latest",
            "requires_secrets",
            "usage_count",
            "created_by",
            "updated_at",
        )
        read_only_fields = fields

    def get_usage_count(self, obj: AgentCustomToolTemplate) -> int:
        return AgentRevisionCustomToolTemplate.objects.filter(tool_template__name=obj.name).count()


class CustomToolTemplateDetailSerializer(CustomToolTemplateSummarySerializer):
    # `source` shadows the inherited `Field.source` typed as `Callable | str | None`;
    # DRF lets us reuse the attribute name for a child Field, but mypy can't model that.
    source = serializers.CharField(  # type: ignore[assignment]
        allow_blank=True,
        help_text="TypeScript source the bundler compiles to `compiled_js`.",
    )
    compiled_js = serializers.CharField(
        allow_blank=True,
        help_text="Last bundle output. Copied into `bundle/tools/<alias>/compiled.js` at freeze.",
    )
    args_schema = serializers.JSONField(help_text="TypeBox / JSON Schema for tool args.")
    returns_schema = serializers.JSONField(
        required=False,
        help_text="Optional TypeBox / JSON Schema for the return value (informational).",
    )

    class Meta(CustomToolTemplateSummarySerializer.Meta):
        fields = (
            *CustomToolTemplateSummarySerializer.Meta.fields,
            "source",
            "compiled_js",
            "args_schema",
            "returns_schema",
        )
        read_only_fields = fields


class CustomToolTemplateCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128, help_text="Slug-shaped name unique per team.")
    description = serializers.CharField(
        max_length=4096, required=False, allow_blank=True, default="", help_text="One-line description."
    )
    source = serializers.CharField(required=False, allow_blank=True, default="", help_text="TypeScript source.")  # type: ignore[assignment]
    compiled_js = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Bundler output. The publisher (UI or MCP) computes this client-side.",
    )
    args_schema = serializers.JSONField(default=dict, help_text="TypeBox / JSON Schema for tool args.")
    returns_schema = serializers.JSONField(
        required=False, default=dict, help_text="Optional TypeBox / JSON Schema for the return value."
    )
    requires_secrets = serializers.ListField(
        child=serializers.CharField(max_length=128),
        required=False,
        default=list,
        help_text="Names of secrets the tool reads via `ctx.secret(...)`.",
    )

    def validate_name(self, value: str) -> str:
        return _validate_template_name(value)

    def validate_source(self, value: str) -> str:
        return _validate_source_size(value)


class CustomToolTemplateEditSerializer(serializers.Serializer):
    """Structured edit applied to source."""

    old = serializers.CharField(allow_blank=False, help_text="Text to locate (must match exactly once).")
    new = serializers.CharField(allow_blank=True, help_text="Replacement text.")


class CustomToolTemplatePublishSerializer(serializers.Serializer):
    description = serializers.CharField(
        max_length=4096,
        required=False,
        allow_blank=True,
        help_text="Overrides the prior description. Omit to keep the prior value.",
    )
    source = serializers.CharField(  # type: ignore[assignment]
        required=False, allow_blank=True, help_text="Full new TypeScript source. Mutually exclusive with `edits`."
    )
    edits = serializers.ListField(
        child=CustomToolTemplateEditSerializer(),
        required=False,
        help_text="Structured edits against the current source.",
    )
    compiled_js = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Updated bundle output. Required when `source` or `edits` are supplied.",
    )
    args_schema = serializers.JSONField(required=False, help_text="Overrides args_schema. Omit to keep prior value.")
    returns_schema = serializers.JSONField(
        required=False, help_text="Overrides returns_schema. Omit to keep prior value."
    )
    requires_secrets = serializers.ListField(
        child=serializers.CharField(max_length=128),
        required=False,
        help_text="Overrides requires_secrets. Omit to keep prior value.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        source_given = "source" in attrs
        edits_given = "edits" in attrs and attrs["edits"]
        if source_given and edits_given:
            raise serializers.ValidationError("Provide either `source` or `edits`, not both.")
        if source_given or edits_given:
            if "compiled_js" not in attrs:
                raise serializers.ValidationError(
                    "`compiled_js` must accompany `source` / `edits` — the bundler runs client-side."
                )
        if "source" in attrs:
            _validate_source_size(attrs["source"])
        return attrs


class CustomToolTemplateDuplicateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128, help_text="Slug for the duplicate.")
    description = serializers.CharField(
        max_length=4096, required=False, allow_blank=True, help_text="Description for the new template."
    )

    def validate_name(self, value: str) -> str:
        return _validate_template_name(value)


class CustomToolTemplateUsageSerializer(serializers.Serializer):
    agent_slug = serializers.CharField(help_text="Slug of the agent whose revision pins this tool.")
    agent_name = serializers.CharField(help_text="Display name of the agent.")
    revision_id = serializers.UUIDField(help_text="Frozen revision id.")
    revision_short_id = serializers.CharField(help_text="First 8 chars of the revision id, for display.")
    pinned_version = serializers.IntegerField(help_text="Tool version pinned at freeze.")


# ─────────────────────────── Version history shape ──────────────────────────


class TemplateVersionEntrySerializer(serializers.Serializer):
    """Read shape used by `…/versions/` on both template families."""

    version = serializers.IntegerField(help_text="Version number.")
    is_latest = serializers.BooleanField(help_text="True for the current row in this version's name lineage.")
    created_by = UserBasicSerializer(allow_null=True, help_text="Publisher. Null for canonical.")
    updated_at = serializers.DateTimeField(help_text="When this version was published.")
