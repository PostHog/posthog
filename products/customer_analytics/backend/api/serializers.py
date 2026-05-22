import json

from drf_spectacular.utils import extend_schema_field
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin

from products.customer_analytics.backend.models import Account, CustomerJourney, CustomerProfileConfig
from products.customer_analytics.backend.models.account import AccountProperties
from products.notebooks.backend.models import Notebook

_ACCOUNT_ASSIGNMENT_SCHEMA = {
    "type": "object",
    "nullable": True,
    "properties": {
        "id": {"type": "integer"},
        "email": {"type": "string"},
    },
    "required": ["id", "email"],
}

_ACCOUNT_PROPERTIES_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "csm": _ACCOUNT_ASSIGNMENT_SCHEMA,
        "account_executive": _ACCOUNT_ASSIGNMENT_SCHEMA,
        "account_owner": _ACCOUNT_ASSIGNMENT_SCHEMA,
        "stripe_customer_id": {"type": "string", "nullable": True},
        "hubspot_deal_id": {"type": "string", "nullable": True},
        "billing_id": {"type": "string", "nullable": True},
        "sfdc_id": {"type": "string", "nullable": True},
        "zendesk_id": {"type": "string", "nullable": True},
    },
}


@extend_schema_field(_ACCOUNT_PROPERTIES_SCHEMA)
class AccountPropertiesField(serializers.JSONField):
    pass


class CustomerProfileConfigSerializer(serializers.ModelSerializer):
    content = serializers.JSONField(required=False, allow_null=True, default=dict)
    sidebar = serializers.JSONField(required=False, allow_null=True, default=dict)

    class Meta:
        model = CustomerProfileConfig
        fields = [
            "id",
            "scope",
            "content",
            "sidebar",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    @staticmethod
    def validate_scope(value):
        if value not in dict(CustomerProfileConfig.Scope.choices):
            raise serializers.ValidationError(
                f"Invalid scope '{value}'. Must be one of: {', '.join(dict(CustomerProfileConfig.Scope.choices).keys())}"
            )
        return value

    def validate_content(self, value):
        return self._validate_json(field="content", value=value)

    def validate_sidebar(self, value):
        return self._validate_json(field="sidebar", value=value)

    def _validate_json(self, field: str, value):
        self.fields[field].run_validation(value)

        if value is None:
            return {}

        if not isinstance(value, dict | list):
            raise serializers.ValidationError(f"Invalid value for field '{field}'")

        try:
            json.dumps(value)
        except (ValueError, TypeError):
            raise serializers.ValidationError(f"Invalid value for field '{field}'")

        return value

    def create(self, validated_data):
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]
        return super().create(validated_data)


class CustomerJourneySerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerJourney
        fields = ["id", "insight", "name", "description", "created_at", "created_by", "updated_at"]
        read_only_fields = ["id", "created_at", "created_by", "updated_at"]

    def validate_insight(self, value):
        if value.team_id != self.context["team_id"]:
            raise serializers.ValidationError("The insight does not belong to this team.")
        return value

    def create(self, validated_data):
        from django.db import IntegrityError

        from posthog.exceptions import Conflict

        validated_data["created_by"] = self.context["request"].user
        validated_data["team_id"] = self.context["team_id"]
        try:
            return super().create(validated_data)
        except IntegrityError:
            raise Conflict("A customer journey already exists for this insight.")


class AccountSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
    """A Customer Analytics account — a logical grouping used to assign customer-success ownership."""

    name = serializers.CharField(
        max_length=400,
        help_text="Human-readable name of the account.",
    )
    external_id = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Identifier for the account in an external system (e.g. CRM ID). Optional.",
    )
    properties = AccountPropertiesField(
        source="_properties",
        required=False,
        allow_null=True,
        help_text=(
            "Typed account properties: assignment fields (csm, account_executive, account_owner) "
            "and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, "
            "sfdc_id, zendesk_id). Defaults to an empty object. Unknown keys are rejected."
        ),
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Tag names attached to the account. Pass a list to replace existing tags.",
    )
    notebooks = serializers.SerializerMethodField(
        help_text=(
            "Short IDs of the internal notebooks linked to this account, used to persist investigations, "
            "call notes, and other free-form context. Empty list if no notebooks have been created for the account."
        )
    )

    class Meta:
        model = Account
        fields = [
            "id",
            "name",
            "external_id",
            "properties",
            "tags",
            "notebooks",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "notebooks",
            "created_at",
            "created_by",
            "updated_at",
        ]

    @extend_schema_field({"type": "array", "items": {"type": "string"}})
    def get_notebooks(self, obj: Account) -> list[str]:
        return [link.notebook.short_id for link in obj.notebooks.all()]

    def validate_properties(self, value):
        if value is None:
            return {}

        if not isinstance(value, dict):
            raise serializers.ValidationError("properties must be a JSON object.")

        try:
            json.dumps(value)
        except (TypeError, ValueError):
            raise serializers.ValidationError("properties must be JSON-serializable.")

        try:
            AccountProperties.model_validate(value)
        except PydanticValidationError as exc:
            raise serializers.ValidationError(_format_pydantic_errors(exc))

        return value

    def create(self, validated_data):
        from django.db import IntegrityError

        from posthog.exceptions import Conflict

        validated_data["created_by"] = self.context["request"].user
        validated_data["team_id"] = self.context["team_id"]
        try:
            return super().create(validated_data)
        except IntegrityError:
            raise Conflict("An account with this external_id already exists for this team.")


def _format_pydantic_errors(exc: PydanticValidationError) -> list[str]:
    messages = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        messages.append(f"{loc}: {err['msg']}" if loc else err["msg"])
    return messages


class AccountNotebookSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)
    title = serializers.CharField(
        max_length=256,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Human-readable title of the account notebook.",
    )
    content = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="Notebook content as a ProseMirror JSON document structure.",
    )
    text_content = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Plain text representation of the notebook content for search.",
    )

    class Meta:
        model = Notebook
        fields = [
            "id",
            "short_id",
            "title",
            "content",
            "text_content",
            "created_at",
            "created_by",
            "last_modified_at",
            "last_modified_by",
        ]
        read_only_fields = [
            "id",
            "short_id",
            "created_at",
            "created_by",
            "last_modified_at",
            "last_modified_by",
        ]
