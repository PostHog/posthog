import json

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.schema import PersonPropertyFilter


@extend_schema_field({"type": "string", "description": "JSON array of person property filters."})
class AccountPersonFiltersField(serializers.CharField):
    def to_internal_value(self, data: object) -> list[PersonPropertyFilter]:
        raw = super().to_internal_value(data)
        try:
            filters = json.loads(raw)
            if not isinstance(filters, list) or len(filters) > 50:
                raise ValueError()
            return [PersonPropertyFilter.model_validate(item) for item in filters]
        except (ValueError, TypeError):
            raise serializers.ValidationError("Use a JSON array of up to 50 person property filters.")


@extend_schema_field({"type": "string", "description": "JSON array of person property keys."})
class AccountPersonSelectionField(serializers.CharField):
    def to_internal_value(self, data: object) -> list[str]:
        raw = super().to_internal_value(data)
        try:
            keys = json.loads(raw)
        except (ValueError, TypeError):
            raise serializers.ValidationError("Use a JSON array of person property keys.")
        if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
            raise serializers.ValidationError("Use a JSON array of person property keys.")
        return serializers.ListField(child=serializers.CharField(max_length=200), max_length=50).run_validation(keys)


class AccountPersonsQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(default=100, min_value=1, max_value=500, help_text="Page size, from 1 to 500.")
    offset = serializers.IntegerField(default=0, min_value=0, max_value=100000, help_text="Number of persons to skip.")
    search = serializers.CharField(
        default="",
        allow_blank=True,
        max_length=200,
        help_text="Search visible name and email, person ID, and distinct IDs.",
    )
    properties = AccountPersonFiltersField(
        required=False, max_length=50000, help_text="JSON array of person property filters."
    )
    select = AccountPersonSelectionField(
        required=False, max_length=15000, help_text="JSON array of up to 50 person property keys to return."
    )
    order_by = serializers.CharField(
        default="-account_last_seen",
        max_length=201,
        help_text="account_last_seen, account_first_seen, or a selected property key. Prefix with - for descending order.",
    )

    def validate(self, attrs: dict) -> dict:
        attrs.setdefault("select", [])
        key = attrs["order_by"].removeprefix("-")
        if key not in ("account_first_seen", "account_last_seen") and key not in attrs["select"]:
            raise serializers.ValidationError({"order_by": "Sort by account activity or a selected property."})
        attrs["select"] = list(dict.fromkeys(attrs["select"]))
        return attrs


@extend_schema_field(
    {
        "type": "object",
        "additionalProperties": {
            "oneOf": [
                {"type": "string"},
                {"type": "number"},
                {"type": "boolean"},
                {"type": "object", "additionalProperties": {}},
                {"type": "array", "items": {}},
            ],
            "nullable": True,
        },
    }
)
class AccountPersonPropertiesField(serializers.JSONField):
    pass


class AccountPersonSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Current person UUID.")
    name = serializers.CharField(
        help_text="Display name from visible current person properties, falling back to the UUID."
    )
    distinct_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text="Current distinct IDs associated with this account, for person navigation.",
    )
    properties = AccountPersonPropertiesField(help_text="Selected visible current person properties.")
    account_first_seen = serializers.DateTimeField(
        help_text="Earliest account activity across this person's current membership distinct IDs, in UTC."
    )
    account_last_seen = serializers.DateTimeField(
        help_text="Latest account activity across this person's current membership distinct IDs, in UTC."
    )


class AccountPersonsResponseSerializer(serializers.Serializer):
    membership_ready = serializers.BooleanField(
        read_only=True,
        default=True,
        help_text="Whether account membership data is ready. When false, results are empty. Try again later.",
    )
    results = AccountPersonSerializer(many=True, help_text="Current persons associated with this account.")
    limit = serializers.IntegerField(help_text="Requested page size.")
    offset = serializers.IntegerField(help_text="Requested page offset.")
    has_more = serializers.BooleanField(help_text="Whether another page exists.")
