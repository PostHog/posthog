"""
DRF serializers for business_knowledge.

Output: `KnowledgeSourceSerializer` is a DataclassSerializer over the DTO so
the generated TypeScript types follow the contract automatically.

Input: `CreateTextSourceSerializer` validates the raw text payload. Size /
quota checks that need DB access live in logic.py and are raised during
create_text_source inside the transaction.
"""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.security.url_validation import is_url_allowed

from .. import url_fetch
from ..facade.contracts import KnowledgeSourceDTO
from ..facade.enums import MAX_TEXT_SIZE_BYTES, SourceType


class KnowledgeSourceSerializer(DataclassSerializer):
    class Meta:
        dataclass = KnowledgeSourceDTO


class CreateTextSourceSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=255,
        help_text="Short human label for the source. Shown in the settings list and in agent citations.",
    )
    text = serializers.CharField(
        trim_whitespace=False,
        help_text=(
            "Raw text to index. Capped at 1 MB; larger payloads should be split into multiple sources "
            "or wait for URL/file support in Stage 2/3."
        ),
    )

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be blank.")
        return value

    def validate_text(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Text cannot be blank.")
        # Mirror the logic.py byte cap here so we can 400 before opening a transaction.
        if len(value.encode("utf-8")) > MAX_TEXT_SIZE_BYTES:
            raise serializers.ValidationError(
                f"Text exceeds the {MAX_TEXT_SIZE_BYTES:,}-byte cap. Split it into smaller sources."
            )
        return value

    def to_internal_value(self, data: dict) -> dict:
        attrs = super().to_internal_value(data)
        # Pin the source_type server-side — clients cannot opt into url/file
        # via this endpoint. Those get their own endpoints in Stage 2/3.
        attrs["source_type"] = SourceType.TEXT.value
        return attrs


class UpdateTextSourceSerializer(serializers.Serializer):
    """
    PATCH payload for text sources. Both fields optional, at least one
    required. `text` triggers a re-chunk; `name` alone does not.
    """

    name = serializers.CharField(
        max_length=255,
        required=False,
        help_text="New human label for the source.",
    )
    text = serializers.CharField(
        required=False,
        trim_whitespace=False,
        help_text="Replacement text. Omit to keep the existing content.",
    )

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be blank.")
        return value

    def validate_text(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Text cannot be blank.")
        if len(value.encode("utf-8")) > MAX_TEXT_SIZE_BYTES:
            raise serializers.ValidationError(
                f"Text exceeds the {MAX_TEXT_SIZE_BYTES:,}-byte cap. Split it into smaller sources."
            )
        return value

    def validate(self, attrs: dict) -> dict:
        if "name" not in attrs and "text" not in attrs:
            raise serializers.ValidationError("Provide at least one of `name` or `text`.")
        return attrs


class CreateUrlSourceSerializer(serializers.Serializer):
    """
    POST payload for URL sources. Normalizes + SSRF-validates the URL here
    so the client gets a precise 400 instead of a created-but-errored source.
    The logic layer re-validates on every fetch anyway — this is UX, not
    security.
    """

    name = serializers.CharField(
        max_length=255,
        help_text="Short human label for the source. Shown in the settings list and in agent citations.",
    )
    url = serializers.URLField(
        max_length=2048,
        help_text=(
            "Public HTTP(S) URL to fetch. Private / internal hosts are rejected. "
            "Stage 2a fetches this URL once at create time; Stage 2c will refresh it on a schedule."
        ),
    )

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be blank.")
        return value

    def validate_url(self, value: str) -> str:
        try:
            normalized = url_fetch.normalize_url(value)
        except url_fetch.UrlFetchError:
            raise serializers.ValidationError("Invalid URL.")
        allowed, reason = is_url_allowed(normalized)
        if not allowed:
            # Don't echo the exact SSRF reason — it's a reconnaissance aid.
            # A generic message is enough for the user.
            raise serializers.ValidationError("URL is not reachable.")
        return normalized

    def to_internal_value(self, data: dict) -> dict:
        attrs = super().to_internal_value(data)
        attrs["source_type"] = SourceType.URL.value
        return attrs
