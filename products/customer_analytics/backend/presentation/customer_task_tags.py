from rest_framework import serializers

from posthog.api.tagged_item import TAG_NAME_MAX_LENGTH
from posthog.models.tag import tagify

from products.customer_analytics.backend.facade.constants import CUSTOMER_TASK_MAX_TAGS


def validate_customer_task_tag_name(value: str) -> None:
    if len(tagify(value)) > TAG_NAME_MAX_LENGTH:
        raise serializers.ValidationError(f"Use at most {TAG_NAME_MAX_LENGTH} characters after lowercasing the tag.")


def create_customer_task_tags_field(help_text: str = "", *, allow_blank: bool = False) -> serializers.ListField:
    return serializers.ListField(
        child=serializers.CharField(
            max_length=TAG_NAME_MAX_LENGTH, allow_blank=allow_blank, validators=[validate_customer_task_tag_name]
        ),
        required=False,
        max_length=CUSTOMER_TASK_MAX_TAGS,
        help_text=help_text,
    )
