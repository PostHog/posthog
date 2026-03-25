import os
import re
from typing import Any, get_args

from django.core.exceptions import ImproperlyConfigured

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import build_basic_type, build_mock_request, build_parameter_type
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    PolymorphicProxySerializer,
    extend_schema,  # noqa: F401
    extend_schema_field,
    extend_schema_serializer,  # noqa: F401
)  # # noqa: F401 for easy import
from rest_framework import fields, serializers
from rest_framework.exceptions import PermissionDenied

from posthog.models.entity import MathType
from posthog.models.feature_flag.types import PropertyFilterType
from posthog.models.property import OperatorType, PropertyType
from posthog.permissions import APIScopePermission

# Path parameters that are resolved at runtime by TeamAndOrgViewSetMixin and
# therefore cannot be derived from any model field.  We pre-supply their
# OpenAPI types so drf-spectacular never falls through to the warning path.
_KNOWN_PATH_PARAMS: dict[str, dict[str, Any]] = {
    "project_id": {"schema": build_basic_type(OpenApiTypes.STR), "description": ""},
    "environment_id": {"schema": build_basic_type(OpenApiTypes.STR), "description": ""},
    "organization_id": {"schema": build_basic_type(OpenApiTypes.STR), "description": ""},
    "plugin_config_id": {"schema": build_basic_type(OpenApiTypes.INT), "description": ""},
}


class PostHogAutoSchema(AutoSchema):
    """AutoSchema subclass that silences path-parameter warnings for params
    handled by TeamAndOrgViewSetMixin (project_id, environment_id, etc.)."""

    def _resolve_path_parameters(self, variables):
        known = []
        remaining = []
        for var in variables:
            if var in _KNOWN_PATH_PARAMS:
                known.append(
                    build_parameter_type(
                        name=var,
                        location=OpenApiParameter.PATH,
                        description=_KNOWN_PATH_PARAMS[var]["description"],
                        schema=_KNOWN_PATH_PARAMS[var]["schema"],
                    )
                )
            else:
                remaining.append(var)
        return known + super()._resolve_path_parameters(remaining)


def build_openapi_mock_request(method, path, view, original_request, **kwargs):
    request = build_mock_request(method, path, view, original_request, **kwargs)

    if os.getenv("OPENAPI_MOCK_INTERNAL_API_SECRET") == "1":
        from django.conf import settings

        request.META["HTTP_X_INTERNAL_API_SECRET"] = settings.INTERNAL_API_SECRET

    return request


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


class PersonalAPIKeyScheme(OpenApiAuthenticationExtension):
    target_class = "posthog.auth.PersonalAPIKeyAuthentication"
    name = "PersonalAPIKeyAuth"

    def get_security_requirement(self, auto_schema):
        view = auto_schema.view
        request = view.request

        for permission in auto_schema.view.get_permissions():
            if isinstance(permission, APIScopePermission):
                try:
                    scopes = permission._get_required_scopes(request, view)
                    if not scopes:
                        return []
                    return [{self.name: scopes}]
                except (PermissionDenied, ImproperlyConfigured):
                    # NOTE: This should never happen - it indicates that we shouldn't be including it in the docs
                    pass

        # Return empty array if no scopes found
        return []

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer"}


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


class StringPropertyFilterSerializer(_PropertyFilterBase):
    """Matches string values with text-oriented operators."""

    value = serializers.CharField(
        help_text="String value to match against.",
        required=True,
    )
    operator = serializers.ChoiceField(
        choices=["exact", "is_not", "icontains", "not_icontains", "regex", "not_regex"],
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


class DatePropertyFilterSerializer(_PropertyFilterBase):
    """Matches date/datetime values with date-specific operators."""

    value = serializers.CharField(
        help_text="Date or datetime string in ISO 8601 format (e.g. '2024-01-15' or '2024-01-15T10:30:00Z').",
        required=True,
    )
    operator = serializers.ChoiceField(
        choices=["is_date_exact", "is_date_before", "is_date_after"],
        default="is_date_exact",
        required=False,
        help_text="Date comparison operator.",
    )


class ExistencePropertyFilterSerializer(_PropertyFilterBase):
    """Checks whether a property is set or not, without comparing values."""

    operator = serializers.ChoiceField(
        choices=["is_set", "is_not_set"],
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
        help_text="Property filter type. Common values are 'person' and 'cohort'.",
    )
    cohort_name = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Resolved cohort name for cohort-type filters.",
    )
    group_type_index = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Group type index when using group-based filters.",
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
        choices=["is_set", "is_not_set"],
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
    super_groups = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        help_text="Additional super condition groups used by experiments.",
    )
    feature_enrollment = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Whether this flag has early access feature enrollment enabled. When true, the flag is evaluated against the person property $feature_enrollment/{flag_key}.",
    )


property_help_text = "Filter events by event property, person property, cohort, groups and more."


class PropertySerializer(serializers.Serializer):
    def run_validation(self, data):
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
        choices=["AND", "OR"],
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


# Global mapping of (path, method) → product folder, populated during preprocessing
_endpoint_product_mapping: dict[tuple[str, str], str] = {}

# Prefix used to identify deprecated environment duplicates in postprocessing.
# Only env paths that duplicate a /api/projects/ path get this prefix (via {environment_id}).
_DEPRECATED_ENV_PREFIX = "/api/environments/{environment_id}/"


def _get_product_from_module(module: str) -> str | None:
    """Extract product folder name from module path like 'products.batch_exports.backend.api'."""
    if module.startswith("products."):
        parts = module.split(".")
        if len(parts) >= 2:
            return parts[1]
    return None


def _extract_env_suffix(path: str) -> str | None:
    """Extract the resource suffix from an /api/environments/ path, or None if not an env path."""
    prefix = "/api/environments/{parent_lookup_team_id}/"
    if path.startswith(prefix):
        return path[len(prefix) :]
    return None


def preprocess_exclude_path_format(endpoints, **kwargs):
    """
    preprocessing hook that filters out {format} suffixed paths, in case
    format_suffix_patterns is used and {format} path params are unwanted.

    Also tracks endpoints registered under both /api/environments/ and
    /api/projects/ (via register_grandfathered_environment_nested_viewset),
    so that environment duplicates can be marked deprecated in postprocessing.
    """
    # For frontend type generation, include INTERNAL views if they have explicit tags
    include_internal = os.environ.get("OPENAPI_INCLUDE_INTERNAL", "").lower() in ("1", "true")

    # Clear previous mapping
    _endpoint_product_mapping.clear()

    # Pass 1: collect all included endpoints and build a set of suffixes that
    # exist under /api/projects/ so we can identify /api/environments/ duplicates.
    included: list[tuple[str, str, str, Any]] = []
    projects_suffixes: set[tuple[str, str]] = set()
    projects_prefix = "/api/projects/{parent_lookup_team_id}/"

    for path, path_regex, method, callback in endpoints:
        if getattr(callback.cls, "param_derived_from_user_current_team", None):
            continue
        if not hasattr(callback.cls, "scope_object") or getattr(callback.cls, "hide_api_docs", False):
            continue
        scope = callback.cls.scope_object
        if scope == "INTERNAL" and not include_internal:
            continue

        included.append((path, path_regex, method, callback))
        if path.startswith(projects_prefix):
            suffix = path[len(projects_prefix) :]
            projects_suffixes.add((suffix, method))

    # Pass 2: keep all endpoints, but mark env duplicates for deprecation in postprocessing.
    # Env duplicates get {environment_id} param (matching _DEPRECATED_ENV_PREFIX), others get {project_id}.
    # drf-spectacular may rewrite other params (e.g. {pk} → {id}) between pre- and postprocessing,
    # so postprocessing identifies deprecated paths by the {environment_id} prefix, not exact match.
    result = []
    for path, path_regex, method, callback in included:
        env_suffix = _extract_env_suffix(path)
        is_env_duplicate = env_suffix is not None and (env_suffix, method) in projects_suffixes

        if is_env_duplicate:
            path = path.replace("{parent_lookup_team_id}", "{environment_id}")
        else:
            path = path.replace("{parent_lookup_team_id}", "{project_id}")
        path = path.replace("{parent_lookup_", "{")

        # Track product folder for auto-tagging
        product = _get_product_from_module(callback.cls.__module__)
        if product:
            _endpoint_product_mapping[(path, method)] = product

        result.append((path, path_regex, method, callback))
    return result


def _fix_pydantic_schema_for_openapi(schema):
    """
    Recursively convert Pydantic v2 JSON Schema to OpenAPI 3.0 compatible schema.

    Pydantic v2 generates valid JSON Schema but not valid OpenAPI 3.0:
    - anyOf with {"type": "null"} -> nullable: true
    - const: "value" -> enum: ["value"]
    """
    if not isinstance(schema, dict):
        return schema

    schema = dict(schema)

    # Handle anyOf with null type (Pydantic's Optional fields)
    if "anyOf" in schema:
        any_of = schema["anyOf"]
        non_null_schemas = [s for s in any_of if not (isinstance(s, dict) and s.get("type") == "null")]
        has_null = any(isinstance(s, dict) and s.get("type") == "null" for s in any_of)

        if has_null and non_null_schemas:
            del schema["anyOf"]
            if len(non_null_schemas) == 1:
                schema.update(_fix_pydantic_schema_for_openapi(non_null_schemas[0]))
                schema["nullable"] = True
            else:
                schema["anyOf"] = [_fix_pydantic_schema_for_openapi(s) for s in non_null_schemas]
                schema["nullable"] = True
        elif non_null_schemas:
            if len(non_null_schemas) == 1:
                del schema["anyOf"]
                schema.update(_fix_pydantic_schema_for_openapi(non_null_schemas[0]))
            else:
                schema["anyOf"] = [_fix_pydantic_schema_for_openapi(s) for s in non_null_schemas]
        else:  # all schemas in anyOf are null types
            schema.clear()
            schema.update({"type": "null", "nullable": True})

    # Literals should be enums in OpenAPI 3.0
    if "const" in schema:
        const_value = schema.pop("const")
        schema["enum"] = [const_value]

    # Recursively fix nested schemas
    if "properties" in schema:
        schema["properties"] = {k: _fix_pydantic_schema_for_openapi(v) for k, v in schema["properties"].items()}

    if "additionalProperties" in schema and isinstance(schema["additionalProperties"], dict):
        schema["additionalProperties"] = _fix_pydantic_schema_for_openapi(schema["additionalProperties"])

    if "items" in schema:
        if isinstance(schema["items"], dict):
            schema["items"] = _fix_pydantic_schema_for_openapi(schema["items"])
        elif isinstance(schema["items"], list):
            schema["items"] = [_fix_pydantic_schema_for_openapi(s) for s in schema["items"]]

    if "allOf" in schema:
        schema["allOf"] = [_fix_pydantic_schema_for_openapi(s) for s in schema["allOf"]]

    if "oneOf" in schema:
        schema["oneOf"] = [_fix_pydantic_schema_for_openapi(s) for s in schema["oneOf"]]

    return schema


def custom_postprocessing_hook(result, generator, request, public):
    all_tags = []
    paths: dict[str, dict] = {}

    for path, methods in result["paths"].items():
        paths[path] = {}
        is_deprecated_env = path.startswith(_DEPRECATED_ENV_PREFIX)

        for method, definition in methods.items():
            if is_deprecated_env:
                definition["deprecated"] = True

            # Preserve explicit tags from @extend_schema before filtering/adding auto-derived ones
            # Exclude auto-derived URL structure tags (projects, environments) - these aren't real product tags
            explicit_tags = [d for d in definition.get("tags", []) if d not in ["projects", "environments"]]

            # Auto-add product tag for ViewSets in products/*/backend/
            product = _endpoint_product_mapping.get((path, method.upper()))
            if product and product not in explicit_tags:
                explicit_tags.append(product)

            definition["x-explicit-tags"] = explicit_tags

            definition["tags"] = [d for d in definition["tags"] if d not in ["projects", "environments"]]
            match = re.search(
                r"((\/api\/(organizations|projects|environments)/{(.*?)}\/)|(\/api\/))(?P<one>[a-zA-Z0-9-_]*)\/",
                path,
            )
            if match:
                definition["tags"].append(match.group("one"))
            for tag in definition["tags"]:
                all_tags.append(tag)

            # Strip router-derived prefixes from operationIds.
            # Keep environments_ on deprecated env paths to avoid collisions with projects_ versions.
            definition["operationId"] = definition["operationId"].replace("organizations_", "", 1)
            if not is_deprecated_env:
                definition["operationId"] = (
                    definition["operationId"].replace("projects_", "", 1).replace("environments_", "", 1)
                )

            if "parameters" in definition:
                definition["parameters"] = [
                    {
                        "in": "path",
                        "name": "project_id",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.",
                    }
                    if param["name"] == "project_id"
                    else {
                        "in": "path",
                        "name": "environment_id",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": "Deprecated. Use /api/projects/{project_id}/ instead.",
                    }
                    if param["name"] == "environment_id"
                    else param
                    for param in definition["parameters"]
                ]
            paths[path][method] = definition

    # Fix type schemas to be OpenAPI 3.0 compatible in a postprocessing hook
    if "components" in result and "schemas" in result["components"]:
        result["components"]["schemas"] = {
            name: _fix_pydantic_schema_for_openapi(schema) for name, schema in result["components"]["schemas"].items()
        }

    return {
        **result,
        "info": {"title": "PostHog API", "version": "1.0.0", "description": ""},
        "paths": paths,
        "x-tagGroups": [{"name": "All endpoints", "tags": sorted(set(all_tags))}],
    }
