"""DRF serializers for dashboards_v2."""

from typing import Any

from drf_spectacular.extensions import OpenApiSerializerFieldExtension
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import ResolvedComponent
from drf_spectacular.utils import Direction
from inflection import camelize
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.shared import UserBasicSerializer

from ..facade.contracts import CreateDashboardV2Input, UpdateDashboardV2Input
from ..facade.spec import Dashboard

# Dashboard, TimeRange and Threshold already name other products' components, so every spec component gets a prefix.
SPEC_COMPONENT_PREFIX = "DashboardV2"


class DashboardSpecField(serializers.DictField):
    """A dashboard document. `DashboardSpecFieldExtension` gives it the schema of the `Dashboard` model."""


class DashboardSpecFieldExtension(OpenApiSerializerFieldExtension):
    target_class = DashboardSpecField

    def get_name(self) -> str:
        return f"{SPEC_COMPONENT_PREFIX}Spec"

    def map_serializer_field(self, auto_schema: AutoSchema, direction: Direction) -> dict[str, Any]:
        schema = Dashboard.model_json_schema(ref_template=f"#/components/schemas/{SPEC_COMPONENT_PREFIX}{{model}}")
        for name, definition in schema.pop("$defs", {}).items():
            component = f"{SPEC_COMPONENT_PREFIX}{name}"
            self._name_enums(auto_schema, component, definition)
            self._register(auto_schema, component, definition)
        self._name_enums(auto_schema, self.get_name(), schema)
        return schema

    def _name_enums(self, auto_schema: AutoSchema, component: str, schema: dict[str, Any]) -> None:
        # An inline enum is named after its property alone, and `language` already names another product's enum.
        for name, prop in schema.get("properties", {}).items():
            holder = prop.get("items", {}) if prop.get("type") == "array" else prop
            if "enum" not in holder:
                continue
            enum = f"{component}{camelize(name)}Enum"
            self._register(auto_schema, enum, {"type": holder["type"], "enum": holder["enum"]})
            holder.clear()
            holder["$ref"] = f"#/components/schemas/{enum}"

    @staticmethod
    def _register(auto_schema: AutoSchema, name: str, schema: dict[str, Any]) -> None:
        auto_schema.registry.register_on_missing(
            ResolvedComponent(name=name, type=ResolvedComponent.SCHEMA, object=name, schema=schema)
        )


class DashboardV2SummarySerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Unique identifier of the dashboard row. API routes use `uid`.")
    uid = serializers.CharField(
        help_text="Identifier of the dashboard in URLs and in its spec. It is unique in the project."
    )
    title = serializers.CharField(help_text="Title from the spec.")
    description = serializers.CharField(
        allow_null=True, allow_blank=True, help_text="Description from the spec, or null when the spec has none."
    )
    folder = serializers.CharField(
        allow_blank=True, help_text="Folder titles from the spec, separated by `/`. Empty for the top level."
    )
    tags = serializers.ListField(child=serializers.CharField(), help_text="Tags from the spec.")
    version = serializers.IntegerField(
        help_text="Number of the latest saved version. It starts at 1, and each save adds 1."
    )
    created_at = serializers.DateTimeField(help_text="When the dashboard was created.")
    created_by = UserBasicSerializer(
        read_only=True, allow_null=True, help_text="User who created the dashboard, or null when unknown."
    )
    last_modified_at = serializers.DateTimeField(help_text="When the dashboard was last saved.")
    last_modified_by = UserBasicSerializer(
        read_only=True, allow_null=True, help_text="User who last saved the dashboard, or null when unknown."
    )


class DashboardV2DetailSerializer(DashboardV2SummarySerializer):
    spec = DashboardSpecField(
        help_text="The dashboard document: its variables, layout and panels. Its keys are camelCase."
    )


class CreateDashboardV2InputSerializer(DataclassSerializer):
    spec = DashboardSpecField(
        help_text="The dashboard document. Its `uid` becomes the uid of the dashboard and must be unused in the project."
    )

    class Meta:
        dataclass = CreateDashboardV2Input


class UpdateDashboardV2InputSerializer(DataclassSerializer):
    spec = DashboardSpecField(
        help_text="The whole dashboard document to save as the next version. Its `uid` must match the URL."
    )

    class Meta:
        dataclass = UpdateDashboardV2Input
        extra_kwargs = {
            "base_version": {
                "min_value": 1,
                "help_text": (
                    "The `version` this save is based on. The save is refused with a 409 when the dashboard "
                    "has a different version. Leave it out to save over any version."
                ),
            },
            "message": {
                "allow_blank": True,
                "help_text": "A note on what changed, stored with the new version.",
            },
        }


class DashboardV2SpecIssueSerializer(serializers.Serializer):
    path = serializers.CharField(help_text="Where the problem is in the spec, for example `panels.orders.viz.type`.")
    message = serializers.CharField(help_text="What is wrong at that path.")


class DashboardV2InvalidSpecExtraSerializer(serializers.Serializer):
    issues = DashboardV2SpecIssueSerializer(many=True, help_text="Every problem found in the spec.")


class DashboardV2InvalidSpecErrorSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="Error category. Always `validation_error`.")
    code = serializers.CharField(help_text="Error code. `invalid_spec` when the spec has the problems in `extra`.")
    detail = serializers.CharField(help_text="The problems as one readable message.")
    attr = serializers.CharField(allow_null=True, help_text="Request field the error is about.")
    extra = DashboardV2InvalidSpecExtraSerializer(required=False, help_text="Present when `code` is `invalid_spec`.")
