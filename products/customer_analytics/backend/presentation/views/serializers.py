"""DRF serializers for the customer_analytics account CRUD presentation layer.

The model-backed viewsets used to bind ``ModelSerializer``s straight to ``Account`` /
``CustomerJourney`` / ``CustomerProfileConfig``. They now serialize the facade's frozen
contracts via ``DataclassSerializer`` instead, so this module no longer imports product
models. Every field is declared explicitly to keep the generated OpenAPI components
(``Account``, ``PatchedAccount``, ``CustomerJourney``, ``CustomerProfileConfig``,
``AccountNotebook``, ``UserBasic`` …) byte-identical to the pre-isolation output.

Each serializer doubles as the viewset's ``serializer_class`` for both request and
response — drf-spectacular derives the request component (and its ``Patched`` variant)
from it exactly as it did for the ``ModelSerializer``s. The contracts carry field
defaults purely so these serializers can instantiate them from partial request bodies;
``required`` / ``read_only`` are pinned here, not by the dataclass.

``AccountOrganizationMemberSerializer`` stays a ``ModelSerializer`` — it is bound to the
core ``OrganizationMembership`` model (no customer_analytics dependency) and is imported
by the sibling ``organization_members`` module.
"""

import json

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.shared import UserBasicSerializer
from posthog.models import OrganizationMembership

from products.customer_analytics.backend.facade.contracts import (
    AccountNotebookView,
    AccountView,
    CustomerJourneyView,
    CustomerProfileConfigView,
    CustomPropertyDefinitionView,
)

# Scope (value, label) pairs, kept in sync with ``CustomerProfileConfig.Scope``. Declared
# here rather than read off the model so this module imports no product models — the
# generated ``CustomerProfileConfigScopeEnum`` stays identical to the model-derived one.
_PROFILE_CONFIG_SCOPE_CHOICES = [
    ("person", "Person"),
    ("group_0", "Group 0"),
    ("group_1", "Group 1"),
    ("group_2", "Group 2"),
    ("group_3", "Group 3"),
    ("group_4", "Group 4"),
]

# Display-type choices for custom property definitions, kept in sync with ``models.DisplayType``.
# Declared here (not read off the model) so this module imports no product models; the generated
# ``CustomPropertyDisplayTypeEnum`` stays identical to the model-derived one (pinned via
# ``ENUM_NAME_OVERRIDES`` in settings).
_CUSTOM_PROPERTY_DISPLAY_TYPE_CHOICES = ["text", "number", "currency", "percent", "date", "datetime", "boolean"]

# JSON schema for the account ``properties`` field. Kept verbatim from the pre-isolation
# serializer so the generated ``AccountApiProperties`` component is unchanged.
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
        "slack_channel_id": {"type": "string", "nullable": True},
        "usage_dashboard_link": {"type": "string", "nullable": True},
    },
}


@extend_schema_field(_ACCOUNT_PROPERTIES_SCHEMA)
class AccountPropertiesField(serializers.JSONField):
    pass


class CustomerProfileConfigSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True)
    scope = serializers.ChoiceField(choices=_PROFILE_CONFIG_SCOPE_CHOICES)
    content = serializers.JSONField(required=False, allow_null=True, default=dict)
    sidebar = serializers.JSONField(required=False, allow_null=True, default=dict)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        dataclass = CustomerProfileConfigView
        # Pin the OpenAPI component name to the pre-isolation one (DataclassSerializer would
        # otherwise name it after the wrapped dataclass, ``CustomerProfileConfigView``).
        ref_name = "CustomerProfileConfig"
        fields = ["id", "scope", "content", "sidebar", "created_at", "updated_at"]

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


class CustomerJourneySerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True)
    insight = serializers.IntegerField()
    name = serializers.CharField(max_length=400)
    description = serializers.CharField(required=False, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
    created_by = serializers.IntegerField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        dataclass = CustomerJourneyView
        ref_name = "CustomerJourney"
        fields = ["id", "insight", "name", "description", "created_at", "created_by", "updated_at"]


class AccountSerializer(DataclassSerializer):
    """A Customer Analytics account — a logical grouping used to assign customer-success ownership."""

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(
        max_length=400,
        help_text="Human-readable name of the account.",
    )
    external_id = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text=(
            "Identifier linking this account to its source customer — the analytics group key "
            "(the customer's organization id), used to match billing and external records. Optional."
        ),
    )
    properties = AccountPropertiesField(
        required=False,
        allow_null=True,
        help_text=(
            "Typed account properties: assignment fields (csm, account_executive, account_owner) "
            "and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, "
            "sfdc_id, zendesk_id, slack_channel_id, usage_dashboard_link). Defaults to an empty "
            "object. Unknown keys are rejected."
        ),
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Tag names attached to the account. Pass a list to replace existing tags.",
    )
    notebooks = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text=(
            "Short IDs of the internal notebooks linked to this account, used to persist investigations, "
            "call notes, and other free-form context. Empty list if no notebooks have been created for the account."
        ),
    )
    created_at = serializers.DateTimeField(read_only=True)
    created_by = serializers.IntegerField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        dataclass = AccountView
        ref_name = "Account"
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

    def validate_properties(self, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("properties must be a JSON object.")
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            raise serializers.ValidationError("properties must be JSON-serializable.")
        return value


class AccountOrganizationMemberSerializer(serializers.ModelSerializer):
    """Slim organization-member representation for Customer analytics account rows."""

    user = UserBasicSerializer(
        read_only=True,
        help_text="Basic profile of the member's user (uuid, distinct_id, first_name, last_name, email).",
    )

    class Meta:
        model = OrganizationMembership
        fields = ["id", "user"]
        read_only_fields = ["id", "user"]
        extra_kwargs = {"id": {"help_text": "Organization membership ID."}}


class AccountNotebookSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True)
    short_id = serializers.CharField(read_only=True)
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
    created_at = serializers.DateTimeField(read_only=True)
    last_modified_at = serializers.DateTimeField(read_only=True)

    class Meta:
        dataclass = AccountNotebookView
        ref_name = "AccountNotebook"
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


class CustomPropertyDefinitionSerializer(DataclassSerializer):
    """A team-scoped definition of a custom account property — the attribute side of the model.

    Holds only the property's shape (name, display type, big-number flag). Per-account values are
    stored separately, so this serializer never reads or writes account values. The numeric-only
    big-number rule and the unique-name conflict are enforced behind the facade.
    """

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(
        max_length=400,
        help_text="Human-readable name of the custom property. Unique within the team.",
    )
    description = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional description of what the property represents.",
    )
    display_type = serializers.ChoiceField(
        choices=_CUSTOM_PROPERTY_DISPLAY_TYPE_CHOICES,
        help_text=(
            "How the property is interpreted and rendered: 'text', 'number', 'currency', "
            "'percent', 'date', 'datetime', or 'boolean'."
        ),
    )
    is_big_number = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Abbreviate large numbers (e.g. 10,000 → 10K). Only applies to numeric properties.",
    )
    created_at = serializers.DateTimeField(read_only=True)
    created_by = serializers.IntegerField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        dataclass = CustomPropertyDefinitionView
        # Pin the OpenAPI component name to the pre-isolation one (DataclassSerializer would
        # otherwise name it after the wrapped dataclass, ``CustomPropertyDefinitionView``).
        ref_name = "CustomPropertyDefinition"
        fields = [
            "id",
            "name",
            "description",
            "display_type",
            "is_big_number",
            "created_at",
            "created_by",
            "updated_at",
        ]
