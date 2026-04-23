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

    def to_internal_value(self, data):
        attrs = super().to_internal_value(data)
        # Pin the source_type server-side — clients cannot opt into url/file
        # via this endpoint. Those get their own endpoints in Stage 2/3.
        attrs["source_type"] = SourceType.TEXT.value
        return attrs
