import json
from typing import Any

from drf_spectacular.utils import extend_schema_field
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers

from posthog.schema import PersonPropertyFilter

from posthog.rate_limit import UserOrEmailRateThrottle

from products.customer_analytics.backend.facade.enums import AccountPersonsSortDirection


class AccountPersonsWebBurstThrottle(UserOrEmailRateThrottle):
    scope = "account_persons_burst"
    rate = "180/minute"


class AccountPersonsWebSustainedThrottle(UserOrEmailRateThrottle):
    scope = "account_persons_sustained"
    rate = "1200/hour"


@extend_schema_field({"type": "string", "format": "json"})
class AccountPersonFiltersField(serializers.Field):
    def to_internal_value(self, data: object) -> list[PersonPropertyFilter]:
        try:
            filters = json.loads(data) if isinstance(data, str) else data
        except ValueError:
            raise serializers.ValidationError("Use a JSON array of person property filters.")
        if not isinstance(filters, list) or len(filters) > 50:
            raise serializers.ValidationError("Use at most 50 person property filters.")
        try:
            return [PersonPropertyFilter.model_validate(item) for item in filters]
        except PydanticValidationError:
            raise serializers.ValidationError("Use valid person property filters.")


@extend_schema_field({"type": "string", "format": "json"})
class AccountPersonPropertiesField(serializers.Field):
    def to_internal_value(self, data: object) -> list[str]:
        try:
            value = json.loads(data) if isinstance(data, str) else data
        except ValueError:
            raise serializers.ValidationError("Use a JSON array of up to 50 property keys.")
        if (
            not isinstance(value, list)
            or len(value) > 50
            or any(not isinstance(key, str) or not key or len(key) > 1000 for key in value)
        ):
            raise serializers.ValidationError("Use a JSON array of up to 50 property keys.")
        return list(dict.fromkeys(value))


class AccountPersonsQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(min_value=1, max_value=500, default=100, help_text="Maximum persons per page.")
    offset = serializers.IntegerField(min_value=0, default=0, help_text="Number of matching persons to skip.")
    search = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        default="",
        help_text="Search name, email, person ID, or distinct ID.",
    )
    properties = AccountPersonPropertiesField(
        default=list,
        help_text='JSON array of selected person property keys. Example: ["email", "name"].',
    )
    filters = AccountPersonFiltersField(
        default=list,
        help_text='JSON array of person property filters with key, operator, value, and type="person". Filters use AND.',
    )
    sort_column = serializers.CharField(
        max_length=1000,
        default="account_last_seen",
        help_text="Sort by id, display_name, account_first_seen, account_last_seen, or a selected property key.",
    )
    sort_direction = serializers.ChoiceField(
        choices=AccountPersonsSortDirection.choices, default="desc", help_text="Sort direction. Person ID breaks ties."
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["sort_column"] not in {
            "id",
            "display_name",
            "account_first_seen",
            "account_last_seen",
            *attrs["properties"],
        }:
            raise serializers.ValidationError({"sort_column": "Select the property before sorting by it."})
        attrs["properties"] = list(dict.fromkeys(attrs["properties"]))
        return attrs


class AccountPersonSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Current person ID.")
    display_name = serializers.CharField(help_text="Display name from visible person properties, or the person ID.")
    distinct_ids = serializers.ListField(
        child=serializers.CharField(), help_text="Current membership distinct IDs for person navigation, up to 101."
    )
    properties = serializers.DictField(
        child=serializers.JSONField(allow_null=True), help_text="Selected visible person properties."
    )
    account_first_seen = serializers.DateTimeField(
        help_text="Earliest account activity across current distinct IDs, in UTC."
    )
    account_last_seen = serializers.DateTimeField(
        help_text="Latest account activity across current distinct IDs, in UTC."
    )


class AccountPersonsPageSerializer(serializers.Serializer):
    results = AccountPersonSerializer(many=True, help_text="Matching current persons for this account.")
    columns = serializers.ListField(
        child=serializers.CharField(), help_text="Selected visible property keys, in request order."
    )
    limit = serializers.IntegerField(help_text="Maximum persons per page.")
    offset = serializers.IntegerField(help_text="Number of matching persons skipped.")
    has_more = serializers.BooleanField(help_text="Whether another page exists.")
    next_offset = serializers.IntegerField(allow_null=True, help_text="Offset of the next page, or null.")
