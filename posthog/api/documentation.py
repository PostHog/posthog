import re
from typing import get_args

from django.core.exceptions import ImproperlyConfigured

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    extend_schema,  # noqa: F401
    extend_schema_field,
    extend_schema_serializer,  # noqa: F401
)  # # noqa: F401 for easy import
from rest_framework import fields, serializers
from rest_framework.exceptions import PermissionDenied

from posthog.models.entity import MathType
from posthog.models.property import OperatorType, PropertyType
from posthog.permissions import APIScopePermission


@extend_schema_field(OpenApiTypes.STR)
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


def preprocess_exclude_path_format(endpoints, **kwargs):
    """
    preprocessing hook that filters out {format} suffixed paths, in case
    format_suffix_patterns is used and {format} path params are unwanted.
    """
    result = []
    for path, path_regex, method, callback in endpoints:
        if getattr(callback.cls, "param_derived_from_user_current_team", None):
            pass
        elif (
            hasattr(callback.cls, "scope_object")
            and callback.cls.scope_object != "INTERNAL"
            and not getattr(callback.cls, "hide_api_docs", False)
        ):
            # If there is an API Scope set then we implictly support it and should have it in the documentation
            path = path.replace(
                "{parent_lookup_team_id}",
                "{project_id}",  # TODO: "{environment_id}" once project environments are rolled out
            )
            path = path.replace("{parent_lookup_", "{")
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
        for method, definition in methods.items():
            definition["tags"] = [d for d in definition["tags"] if d not in ["projects"]]
            match = re.search(
                r"((\/api\/(organizations|projects)/{(.*?)}\/)|(\/api\/))(?P<one>[a-zA-Z0-9-_]*)\/",
                path,
            )
            if match:
                definition["tags"].append(match.group("one"))
            for tag in definition["tags"]:
                all_tags.append(tag)
            definition["operationId"] = (
                definition["operationId"].replace("organizations_", "", 1).replace("projects_", "", 1)
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
