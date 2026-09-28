"""Schema-only serializers for property, feature flag, event and action filters."""

from typing import get_args

from django.db import models

from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from rest_framework import fields, serializers

from posthog.models.entity import MathType
from posthog.models.property import OperatorType, PropertyType

from products.feature_flags.backend.types import PropertyFilterType


@extend_schema_field(
    {
        "oneOf": [
            {"type": "string"},
            {"type": "number"},
            {"type": "boolean"},
            {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}},
        ]
    }
)
class ValueField(serializers.Field):
    def to_representation(self, value):
        return value

    def to_internal_value(self, data):
        return data


class PropertyItemSerializer(serializers.Serializer):
    key = serializers.CharField(
        help_text="Key of the property you're filtering on. For example `email` or `$current_url`",
        required=True,
    )
    value = ValueField(
        help_text='Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `["test@example.com","ok@example.com"]`',
        required=True,
    )
    operator = serializers.ChoiceField(
        choices=get_args(OperatorType),
        required=False,
        allow_blank=True,
        default="exact",
        allow_null=True,
    )
    type = serializers.ChoiceField(
        choices=get_args(PropertyType),
        default="event",
        required=False,
        allow_blank=True,
    )


# ---------------------------------------------------------------------------
# Narrowed property filter serializers (schema-only, not used at runtime)
#
# These produce a oneOf union in the OpenAPI spec so that generated clients
# (TypeScript, MCP tools) see operator/value combinations that actually make
# sense, instead of a single permissive type with all 17 operators.
# ---------------------------------------------------------------------------

_PROPERTY_TYPE_CHOICES = get_args(PropertyType)


class _PropertyFilterBase(serializers.Serializer):
    """Shared fields for all narrowed property filter subtypes."""

    key = serializers.CharField(
        help_text="Key of the property you're filtering on. For example `email` or `$current_url`.",
        required=True,
    )
    type = serializers.ChoiceField(
        choices=_PROPERTY_TYPE_CHOICES,
        default="event",
        required=False,
        help_text="Property type (event, person, session, etc.).",
    )


class StringMatchOperator(models.TextChoices):
    EXACT = "exact", "exact"
    IS_NOT = "is_not", "is_not"
    ICONTAINS = "icontains", "icontains"
    NOT_ICONTAINS = "not_icontains", "not_icontains"
    STARTS_WITH = "starts_with", "starts_with"
    NOT_STARTS_WITH = "not_starts_with", "not_starts_with"
    ENDS_WITH = "ends_with", "ends_with"
    NOT_ENDS_WITH = "not_ends_with", "not_ends_with"
    REGEX = "regex", "regex"
    NOT_REGEX = "not_regex", "not_regex"


class StringPropertyFilterSerializer(_PropertyFilterBase):
    """Matches string values with text-oriented operators."""

    value = serializers.CharField(
        help_text="String value to match against.",
        required=True,
    )
    operator = serializers.ChoiceField(
        choices=StringMatchOperator.choices,
        default="exact",
        required=False,
        help_text="String comparison operator.",
    )


class NumericPropertyFilterSerializer(_PropertyFilterBase):
    """Matches numeric values with comparison operators."""

    value = serializers.FloatField(
        help_text="Numeric value to compare against.",
        required=True,
    )
    operator = serializers.ChoiceField(
        choices=["exact", "is_not", "gt", "lt", "gte", "lte"],
        default="exact",
        required=False,
        help_text="Numeric comparison operator.",
    )


class ArrayPropertyFilterSerializer(_PropertyFilterBase):
    """Matches against a list of values (OR semantics for exact/is_not, set membership for in/not_in)."""

    value = serializers.ListField(
        child=serializers.CharField(),
        help_text='List of values to match. For example `["test@example.com", "ok@example.com"]`.',
        required=True,
    )
    operator = serializers.ChoiceField(
        choices=["exact", "is_not", "in", "not_in"],
        default="exact",
        required=False,
        help_text="Array comparison operator.",
    )


class DateOperator(models.TextChoices):
    IS_DATE_EXACT = "is_date_exact", "is_date_exact"
    IS_DATE_BEFORE = "is_date_before", "is_date_before"
    IS_DATE_AFTER = "is_date_after", "is_date_after"


class DatePropertyFilterSerializer(_PropertyFilterBase):
    """Matches date/datetime values with date-specific operators."""

    value = serializers.CharField(
        help_text="Date or datetime string in ISO 8601 format (e.g. '2024-01-15' or '2024-01-15T10:30:00Z').",
        required=True,
    )
    operator = serializers.ChoiceField(
        choices=DateOperator.choices,
        default="is_date_exact",
        required=False,
        help_text="Date comparison operator.",
    )


class ExistenceOperator(models.TextChoices):
    IS_SET = "is_set", "is_set"
    IS_NOT_SET = "is_not_set", "is_not_set"


class ExistencePropertyFilterSerializer(_PropertyFilterBase):
    """Checks whether a property is set or not, without comparing values."""

    operator = serializers.ChoiceField(
        choices=ExistenceOperator.choices,
        required=True,
        help_text="Existence check operator.",
    )


_FEATURE_FLAG_FILTER_NON_FLAG_TYPE_CHOICES = [
    property_filter_type.value for property_filter_type in PropertyFilterType if property_filter_type.value != "flag"
]


class _FeatureFlagFilterPropertyBaseSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Property key used in this feature flag condition.")
    type = serializers.ChoiceField(
        choices=_FEATURE_FLAG_FILTER_NON_FLAG_TYPE_CHOICES,
        required=False,
        help_text="Property filter type. Set it on every property. Use `group` with `group_type_index` to filter on a group's properties.",
    )
    cohort_name = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Resolved cohort name for cohort-type filters.",
    )
    group_type_index = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Group type index a `group` filter reads properties from. Defaults to the condition set's `aggregation_group_type_index`.",
    )


class FeatureFlagFilterPropertyGenericSchemaSerializer(_FeatureFlagFilterPropertyBaseSerializer):
    value = serializers.JSONField(
        required=True,
        help_text="Comparison value for the property filter. Supports strings, numbers, booleans, and arrays.",
    )
    operator = serializers.ChoiceField(
        choices=[
            "exact",
            "is_not",
            "icontains",
            "not_icontains",
            "starts_with",
            "not_starts_with",
            "ends_with",
            "not_ends_with",
            "regex",
            "not_regex",
            "gt",
            "gte",
            "lt",
            "lte",
        ],
        required=True,
        help_text="Operator used to compare the property value.",
    )


class FeatureFlagFilterPropertyExistsSchemaSerializer(_FeatureFlagFilterPropertyBaseSerializer):
    operator = serializers.ChoiceField(
        choices=ExistenceOperator.choices,
        required=True,
        help_text="Existence operator.",
    )
    value = serializers.JSONField(
        required=False,
        help_text="Optional value. Runtime behavior determines whether this is ignored.",
    )


class FeatureFlagFilterPropertyDateSchemaSerializer(_FeatureFlagFilterPropertyBaseSerializer):
    operator = serializers.ChoiceField(
        choices=["is_date_exact", "is_date_after", "is_date_before"],
        required=True,
        help_text="Date comparison operator.",
    )
    value = serializers.CharField(
        required=True,
        help_text="Date value in ISO format or relative date expression.",
    )


class FeatureFlagFilterPropertySemverSchemaSerializer(_FeatureFlagFilterPropertyBaseSerializer):
    operator = serializers.ChoiceField(
        choices=[
            "semver_gt",
            "semver_gte",
            "semver_lt",
            "semver_lte",
            "semver_eq",
            "semver_neq",
            "semver_tilde",
            "semver_caret",
            "semver_wildcard",
        ],
        required=True,
        help_text="Semantic version comparison operator.",
    )
    value = serializers.CharField(
        required=True,
        help_text="Semantic version string.",
    )


class FeatureFlagFilterPropertyMultiContainsSchemaSerializer(_FeatureFlagFilterPropertyBaseSerializer):
    operator = serializers.ChoiceField(
        choices=["icontains_multi", "not_icontains_multi"],
        required=True,
        help_text="Multi-contains operator.",
    )
    value = serializers.ListField(
        child=serializers.CharField(),
        required=True,
        help_text="List of strings to evaluate against.",
    )


class FeatureFlagFilterPropertyCohortInSchemaSerializer(_FeatureFlagFilterPropertyBaseSerializer):
    type = serializers.ChoiceField(
        choices=["cohort"],
        required=True,
        help_text="Cohort property type required for in/not_in operators.",
    )
    operator = serializers.ChoiceField(
        choices=["in", "not_in"],
        required=True,
        help_text="Membership operator for cohort properties.",
    )
    value = serializers.JSONField(
        required=True,
        help_text="Cohort comparison value (single or list, depending on usage).",
    )


class FeatureFlagFilterPropertyFlagEvaluatesSchemaSerializer(_FeatureFlagFilterPropertyBaseSerializer):
    type = serializers.ChoiceField(
        choices=["flag"],
        required=True,
        help_text="Flag property type required for flag dependency checks.",
    )
    operator = serializers.ChoiceField(
        choices=["flag_evaluates_to"],
        required=True,
        help_text="Operator for feature flag dependency evaluation.",
    )
    value = serializers.JSONField(
        required=True,
        help_text="Value to compare flag evaluation against.",
    )


_FeatureFlagFilterPropertyUnion = PolymorphicProxySerializer(
    component_name="FeatureFlagFilterPropertySchema",
    serializers=[
        FeatureFlagFilterPropertyGenericSchemaSerializer,
        FeatureFlagFilterPropertyExistsSchemaSerializer,
        FeatureFlagFilterPropertyDateSchemaSerializer,
        FeatureFlagFilterPropertySemverSchemaSerializer,
        FeatureFlagFilterPropertyMultiContainsSchemaSerializer,
        FeatureFlagFilterPropertyCohortInSchemaSerializer,
        FeatureFlagFilterPropertyFlagEvaluatesSchemaSerializer,
    ],
    resource_type_field_name=None,
)


@extend_schema_field(serializers.ListSerializer(child=_FeatureFlagFilterPropertyUnion))
class FeatureFlagFilterPropertyListSchemaField(serializers.ListField):
    """ListField with oneOf feature-flag property filter typing for OpenAPI generation."""

    pass


class FeatureFlagConditionGroupSchemaSerializer(serializers.Serializer):
    properties = FeatureFlagFilterPropertyListSchemaField(
        child=serializers.DictField(),
        required=False,
        help_text="Property conditions for this release condition group.",
    )
    rollout_percentage = serializers.FloatField(
        required=False,
        help_text="Rollout percentage for this release condition group.",
    )
    variant = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Variant key override for multivariate flags.",
    )
    aggregation_group_type_index = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Group type index for this condition set. None means person-level aggregation.",
    )


class FeatureFlagMultivariateVariantSchemaSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Unique key for this variant.")
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Human-readable name for this variant.",
    )
    rollout_percentage = serializers.FloatField(help_text="Variant rollout percentage.")


class FeatureFlagMultivariateSchemaSerializer(serializers.Serializer):
    variants = FeatureFlagMultivariateVariantSchemaSerializer(
        many=True,
        help_text="Variant definitions for multivariate feature flags.",
    )


class FeatureFlagFiltersSchemaSerializer(serializers.Serializer):
    groups = FeatureFlagConditionGroupSchemaSerializer(
        many=True,
        required=False,
        help_text="Release condition groups for the feature flag.",
    )
    multivariate = FeatureFlagMultivariateSchemaSerializer(
        required=False,
        allow_null=True,
        help_text="Multivariate configuration for variant-based rollouts.",
    )
    aggregation_group_type_index = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Group type index for group-based feature flags.",
    )
    payloads = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        required=False,
        help_text="Optional payload values keyed by variant key.",
    )
    feature_enrollment = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Whether this flag has early access feature enrollment enabled. When true, the flag is evaluated against the person property $feature_enrollment/{flag_key}.",
    )
    early_exit = serializers.BooleanField(
        required=False,
        default=False,
        help_text="When true, condition evaluation stops at the first matching condition set rather than continuing to evaluate subsequent groups.",
    )


property_help_text = "Filter events by event property, person property, cohort, groups and more."


class PropertyGroupOperator(models.TextChoices):
    AND = "AND", "AND"
    OR = "OR", "OR"


class PropertySerializer(serializers.Serializer):
    def run_validation(self, data=fields.empty):
        if isinstance(data, list):
            items = []
            for item in data:
                # allow old style properties to be sent as well
                data = PropertyItemSerializer(data=item)
                data.is_valid(raise_exception=True)
                items.append(data.data)
            return items
        elif not data or data == fields.empty:  # empty dict
            return data
        elif data.get("key") and data.get("value"):
            # if only one item is sent in properties in a GET request, DRF does something weird and exists the dict out
            serializer = PropertyItemSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            return serializer.data
        else:
            return super().run_validation(data)

    type = serializers.ChoiceField(
        help_text="""
 You can use a simplified version:
```json
{
    "properties": [
        {
            "key": "email",
            "value": "x@y.com",
            "operator": "exact",
            "type": "event"
        }
    ]
}
```

Or you can create more complicated queries with AND and OR:
```json
{
    "properties": {
        "type": "AND",
        "values": [
            {
                "type": "OR",
                "values": [
                    {"key": "email", ...},
                    {"key": "email", ...}
                ]
            },
            {
                "type": "AND",
                "values": [
                    {"key": "email", ...},
                    {"key": "email", ...}
                ]
            }
        ]
    ]
}
```
""",
        choices=PropertyGroupOperator.choices,
        default="AND",
    )
    values = PropertyItemSerializer(many=True, required=True)


class PropertiesSerializer(serializers.Serializer):
    properties = PropertySerializer(required=False, many=True, help_text=property_help_text)


class PersonPropertiesSerializer(serializers.Serializer):
    properties = PropertySerializer(required=False, many=True, help_text="Filter Persons by person properties.")


math_help_text = """How to aggregate results, shown as \"counted by\" in the interface.
- `total` (default): no aggregation, count by events
- `dau`: count by unique users. Despite the name, if you select the `interval` to be weekly or monthly, this will show weekly or monthly active users respectively
- `weekly_active`: rolling average of users of the last 7 days.
- `monthly_active`: rolling average of users of the last month.
- `unique_group`: count by group. Requires `math_group_type_index` to be sent. You can get the index by hitting `/api/projects/@current/groups_types/`.

All of the below are property aggregations, and require `math_property` to be sent with an event property.
- `sum`: sum of a numeric property.
- `min`: min of a numeric property.
- `max`: max of a numeric property.
- `median`: median of a numeric property.
- `p75`: 75th percentile of a numeric property.
- `p90`: 90th percentile of a numeric property.
- `p95` 95th percentile of a numeric property.
- `p99`: 99th percentile of a numeric property.
"""


class FilterEventSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Name of the event to filter on. For example `$pageview` or `user sign up`.")
    properties = PropertySerializer(many=True, required=False)
    math = serializers.ChoiceField(
        help_text=math_help_text,
        choices=get_args(MathType),
        default="total",
        required=False,
    )


class FilterActionSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="ID of the action to filter on. For example `2841`.")
    properties = PropertySerializer(many=True, required=False)
    math = serializers.ChoiceField(
        help_text=math_help_text,
        choices=get_args(MathType),
        default="total",
        required=False,
    )
