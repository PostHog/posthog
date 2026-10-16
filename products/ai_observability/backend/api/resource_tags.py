from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.models.tag import tagify

from products.ai_observability.backend.resource_tags import ResourceTags, TagMatch

if TYPE_CHECKING:
    from products.ai_observability.backend.resource_tags import TaggedResource

MAX_RESOURCE_TAGS = 100
MAX_FILTER_TAGS = 20


class ResourceTagNameField(serializers.CharField):
    def to_internal_value(self, data: str) -> str:
        return tagify(super().to_internal_value(data))


class ResourceTagNamesField(serializers.ListField):
    child = ResourceTagNameField(max_length=255, allow_blank=False)

    def __init__(self, *, required: bool = True, max_length: int = MAX_RESOURCE_TAGS) -> None:
        super().__init__(
            required=required,
            max_length=max_length,
            help_text="Tag names. Replaces existing tags; send [] to remove all tags. Names are trimmed and lowercased.",
        )

    def to_internal_value(self, data: object) -> list[str]:
        return sorted(set(super().to_internal_value(cast(list[str], data))))


class ResourceTagsWriteSerializer(serializers.Serializer):
    tags = ResourceTagNamesField(required=False)


class ResourceTagsReadSerializer(serializers.Serializer):
    tags = serializers.SerializerMethodField(help_text="Project tag names assigned to this resource.")

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_tags(self, resource: TaggedResource) -> list[str]:
        return ResourceTags.names(resource)


@extend_schema_field(serializers.CharField(max_length=26000))
class ResourceTagFilterField(serializers.Field):
    def __init__(self) -> None:
        super().__init__(
            required=False,
            help_text='JSON array of tag names, for example ["quality","production"]. Up to 20 tags. An empty array disables tag filtering.',
        )

    def to_internal_value(self, data: object) -> list[str]:
        value = serializers.CharField(max_length=26000).run_validation(data)
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError) as error:
            raise serializers.ValidationError("Supply a JSON array of tag names.") from error
        return ResourceTagNamesField(max_length=MAX_FILTER_TAGS).run_validation(parsed)


class ResourceTagFilterSerializer(serializers.Serializer):
    tags = ResourceTagFilterField()
    tag_match = serializers.ChoiceField(
        choices=TagMatch.choices,
        default=TagMatch.ANY,
        required=False,
        help_text="Match any selected tag (OR) or all selected tags (AND). Additional tags are allowed.",
    )
