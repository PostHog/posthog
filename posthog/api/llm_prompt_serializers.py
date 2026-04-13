import re
import json
from typing import Any

from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.models.llm_prompt import LLMPrompt, normalize_prompt_to_string

RESERVED_PROMPT_NAMES = {"new"}
DEFAULT_VERSION_PAGE_SIZE = 50
MAX_PROMPT_PAYLOAD_BYTES = 1_000_000


def validate_prompt_name_value(value: str) -> str:
    if value.lower() in RESERVED_PROMPT_NAMES:
        raise serializers.ValidationError(
            "'new' is a reserved name and cannot be used.",
            code="reserved_name",
        )
    if not re.match(r"^[a-zA-Z0-9_-]+$", value):
        raise serializers.ValidationError(
            "Only letters, numbers, hyphens (-) and underscores (_) are allowed.",
            code="invalid_name",
        )
    return value


def validate_prompt_payload_size(prompt_payload: Any) -> Any:
    prompt_payload_bytes = len(json.dumps(prompt_payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    if prompt_payload_bytes > MAX_PROMPT_PAYLOAD_BYTES:
        raise serializers.ValidationError(
            f"Prompt payload must be {MAX_PROMPT_PAYLOAD_BYTES} bytes or fewer.",
            code="max_size",
        )
    return prompt_payload


class LLMPromptFetchQuerySerializer(serializers.Serializer):
    version = serializers.IntegerField(
        min_value=1,
        required=False,
        help_text="Specific prompt version to fetch. If omitted, the latest version is returned.",
    )


class LLMPromptListQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional substring filter applied to prompt names and prompt content.",
    )
    content = serializers.ChoiceField(
        choices=["full", "preview", "none"],
        required=False,
        default="full",
        help_text=(
            "Controls how much prompt content is included in list results. "
            "'full' includes the full prompt, 'preview' includes a short prompt_preview, "
            "and 'none' omits prompt content entirely."
        ),
    )


class LLMPromptResolveQuerySerializer(LLMPromptFetchQuerySerializer):
    version_id = serializers.UUIDField(
        required=False,
        help_text="Exact prompt version UUID to resolve. Can be used together with version for extra safety.",
    )
    offset = serializers.IntegerField(
        min_value=0,
        required=False,
        help_text="Zero-based offset into version history for pagination. Mutually exclusive with before_version.",
    )
    before_version = serializers.IntegerField(
        min_value=1,
        required=False,
        help_text="Return versions older than this version number. Mutually exclusive with offset.",
    )
    limit = serializers.IntegerField(
        min_value=1,
        required=False,
        default=DEFAULT_VERSION_PAGE_SIZE,
        max_value=100,
        help_text="Maximum number of versions to return per page (1-100).",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("offset") is not None and attrs.get("before_version") is not None:
            raise serializers.ValidationError("Use either offset or before_version, not both.")
        return attrs


class LLMPromptEditOperationSerializer(serializers.Serializer):
    old = serializers.CharField(
        help_text="Text to find in the current prompt. Must match exactly once.",
    )
    new = serializers.CharField(
        help_text="Replacement text.",
    )


class LLMPromptPublishSerializer(serializers.Serializer):
    prompt = serializers.JSONField(
        required=False,
        help_text="Full prompt payload to publish as a new version. Mutually exclusive with edits.",
    )
    edits = LLMPromptEditOperationSerializer(
        many=True,
        required=False,
        help_text=(
            "List of find/replace operations to apply to the current prompt version. "
            "Each edit's 'old' text must match exactly once. Edits are applied sequentially. "
            "Mutually exclusive with prompt."
        ),
    )
    base_version = serializers.IntegerField(
        min_value=1,
        help_text="Latest version you are editing from. Used for optimistic concurrency checks.",
    )

    def validate_prompt(self, value: Any) -> Any:
        return validate_prompt_payload_size(value)

    def validate_edits(self, value: list[dict[str, str]]) -> list[dict[str, str]]:
        if len(value) == 0:
            raise serializers.ValidationError("At least one edit operation is required.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        has_prompt = "prompt" in attrs
        has_edits = "edits" in attrs

        if has_prompt and has_edits:
            raise serializers.ValidationError("Provide either 'prompt' or 'edits', not both.")
        if not has_prompt and not has_edits:
            raise serializers.ValidationError("Either 'prompt' or 'edits' is required.")

        return attrs


class LLMPromptSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    is_latest = serializers.SerializerMethodField()
    latest_version = serializers.SerializerMethodField()
    version_count = serializers.SerializerMethodField()
    first_version_created_at = serializers.SerializerMethodField()

    class Meta:
        model = LLMPrompt
        fields = [
            "id",
            "name",
            "prompt",
            "version",
            "created_by",
            "created_at",
            "updated_at",
            "deleted",
            "is_latest",
            "latest_version",
            "version_count",
            "first_version_created_at",
        ]
        read_only_fields = [
            "id",
            "version",
            "created_by",
            "created_at",
            "updated_at",
            "deleted",
            "is_latest",
            "latest_version",
            "version_count",
            "first_version_created_at",
        ]
        extra_kwargs = {
            "name": {"help_text": "Unique prompt name using letters, numbers, hyphens, and underscores only."},
            "prompt": {"help_text": "Prompt payload as JSON or string data."},
        }

    def get_is_latest(self, instance: LLMPrompt) -> bool:
        return bool(getattr(instance, "is_latest", False))

    def get_latest_version(self, instance: LLMPrompt) -> int:
        return int(getattr(instance, "latest_version", instance.version))

    def get_version_count(self, instance: LLMPrompt) -> int:
        return int(getattr(instance, "version_count", 1))

    def get_first_version_created_at(self, instance: LLMPrompt) -> str:
        value = getattr(instance, "first_version_created_at", instance.created_at)
        if value is None:
            value = instance.created_at
        if isinstance(value, str):
            return value
        return value.isoformat().replace("+00:00", "Z")

    def to_representation(self, instance: LLMPrompt) -> dict[str, Any]:
        data = super().to_representation(instance)
        if "prompt" in data:
            data["prompt"] = normalize_prompt_to_string(data["prompt"])
        return data

    def validate_name(self, value: str) -> str:
        return validate_prompt_name_value(value)

    def validate_prompt(self, value: Any) -> Any:
        return validate_prompt_payload_size(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        team = self.context["get_team"]()
        name = attrs.get("name")

        if self.instance is None:
            if name and LLMPrompt.objects.filter(name=name, team=team, deleted=False).exists():
                raise serializers.ValidationError({"name": "A prompt with this name already exists."}, code="unique")
            return attrs

        if name is not None and self.instance.name != name:
            raise serializers.ValidationError(
                {"name": "Prompt name cannot be changed after creation."},
                code="immutable",
            )

        if "prompt" in attrs:
            raise serializers.ValidationError(
                {"prompt": "Prompt content is versioned and cannot be updated in place. Create a new version instead."},
                code="immutable",
            )

        return attrs

    def create(self, validated_data: dict[str, Any]) -> LLMPrompt:
        request = self.context["request"]
        team = self.context["get_team"]()

        return LLMPrompt.objects.create(
            team=team,
            created_by=request.user,
            is_latest=True,
            **validated_data,
        )


class LLMPromptListSerializer(LLMPromptSerializer):
    prompt_size_bytes = serializers.SerializerMethodField()
    prompt_preview = serializers.SerializerMethodField()

    class Meta(LLMPromptSerializer.Meta):
        fields = [*LLMPromptSerializer.Meta.fields, "prompt_preview", "prompt_size_bytes"]
        read_only_fields = fields

    def get_prompt_size_bytes(self, instance: LLMPrompt) -> int:
        return int(getattr(instance, "prompt_size_bytes", 0))

    def get_prompt_preview(self, instance: LLMPrompt) -> str:
        prompt = instance.prompt
        display_value = prompt if isinstance(prompt, str) else json.dumps(prompt, ensure_ascii=False)
        return display_value[:160] + ("..." if len(display_value) > 160 else "")

    def to_representation(self, instance: LLMPrompt) -> dict[str, Any]:
        data = super().to_representation(instance)
        content_mode = self.context.get("content_mode", "full")
        if content_mode == "none":
            data.pop("prompt", None)
            data.pop("prompt_preview", None)
        elif content_mode == "preview":
            data.pop("prompt", None)
        else:
            data.pop("prompt_preview", None)
        return data


class LLMPromptVersionSummarySerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = LLMPrompt
        fields = [
            "id",
            "version",
            "created_by",
            "created_at",
            "is_latest",
        ]
        read_only_fields = fields


class LLMPromptPublicSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    prompt = serializers.JSONField()
    version = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    deleted = serializers.BooleanField()
    is_latest = serializers.BooleanField()
    latest_version = serializers.IntegerField()
    version_count = serializers.IntegerField()
    first_version_created_at = serializers.DateTimeField()


class LLMPromptDuplicateSerializer(serializers.Serializer):
    new_name = serializers.CharField(
        max_length=255,
        help_text="Name for the duplicated prompt. Must be unique and use only letters, numbers, hyphens, and underscores.",
    )

    def validate_new_name(self, value: str) -> str:
        return validate_prompt_name_value(value)


class LLMPromptResolveResponseSerializer(serializers.Serializer):
    prompt = LLMPromptSerializer()
    versions = LLMPromptVersionSummarySerializer(many=True)
    has_more = serializers.BooleanField()
