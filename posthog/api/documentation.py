import re
from typing import Dict, get_args

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_field  # for easy import
from rest_framework import serializers

from posthog.models.property import OperatorType, Property, PropertyType


@extend_schema_field(OpenApiTypes.STR)
class ValueField(serializers.Field):
    def to_representation(self, value):
        return value

    def to_internal_value(self, data):
        return data


class PropertySerializer(serializers.Serializer):
    key = serializers.CharField(
        help_text="Key of the property you're filtering on. For example `email` or `$current_url`"
    )
    value = ValueField(
        help_text='Value of your filter. Can be an array. For example `test@example.com` or `https://example.com/test/`. Can be an array, like `["test@example.com","ok@example.com"]`'
    )
    operator = serializers.ChoiceField(choices=get_args(OperatorType), required=False, default="exact")
    type = serializers.ChoiceField(choices=get_args(PropertyType), default="event", required=False)


class PropertiesSerializer(serializers.Serializer):
    properties = PropertySerializer(required=False, many=True)


class FilterEventSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Name of the event to filter on. For example `$pageview` or `user sign up`.")
    properties = PropertySerializer(many=True, required=False)


class FilterActionSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Name of the event to filter on. For example `$pageview` or `user sign up`.")
    properties = PropertySerializer(many=True, required=False)


def preprocess_exclude_path_format(endpoints, **kwargs):
    """
    preprocessing hook that filters out {format} suffixed paths, in case
    format_suffix_patterns is used and {format} path params are unwanted.
    """
    result = []
    for path, path_regex, method, callback in endpoints:
        if hasattr(callback.cls, "legacy_team_compatibility") and callback.cls.legacy_team_compatibility:
            pass
        elif hasattr(callback.cls, "include_in_docs") and callback.cls.include_in_docs:
            path = path.replace("{parent_lookup_team_id}", "{project_id}")
            result.append((path, path_regex, method, callback))
    return result


def custom_postprocessing_hook(result, generator, request, public):
    all_tags = []
    paths: Dict[str, Dict] = {}
    for path, methods in result["paths"].items():
        paths[path] = {}
        for method, definition in methods.items():
            definition["tags"] = [d for d in definition["tags"] if d not in ["projects"]]
            match = re.search(r"((\/api\/(organizations|projects)/{(.*?)}\/)|(\/api\/))(?P<one>[a-zA-Z0-9-_]*)\/", path)
            if match:
                definition["tags"].append(match.group("one"))
                all_tags.append(match.group("one"))
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
    return {
        **result,
        "info": {"title": "PostHog API", "version": None, "description": "",},
        "paths": paths,
        "x-tagGroups": [
            {"name": "Analytics", "tags": ["analytics", "AML", "Customers Timeline"]},
            {"name": "All endpoints", "tags": sorted(list(set(all_tags)))},
        ],
    }
