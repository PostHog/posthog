import uuid
from typing import cast

import structlog
from asgiref.sync import async_to_sync
from drf_spectacular.utils import OpenApiResponse, extend_schema_field
from rest_framework import serializers, viewsets
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User

from products.data_warehouse.backend.sql_chart_spec_ai import (
    SQLChartSpecGenerator,
    SQLChartSpecPayload,
    build_fallback_chart_mapping,
)

logger = structlog.get_logger(__name__)

JSON_VALUE_SCHEMA = {
    "oneOf": [
        {"type": "string"},
        {"type": "number"},
        {"type": "boolean"},
        {"type": "object", "additionalProperties": True},
        {"type": "array", "items": {}},
        {"type": "null"},
    ]
}


@extend_schema_field(JSON_VALUE_SCHEMA)
class JSONValueField(serializers.JSONField):
    pass


class SQLChartColumnSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=256, help_text="Result column name.")
    type = serializers.CharField(
        max_length=128, required=False, allow_null=True, allow_blank=True, help_text="Database column type, if known."
    )
    semanticType = serializers.ChoiceField(
        choices=["temporal", "quantitative", "nominal", "ordinal"],
        required=False,
        help_text="Best-effort semantic type for the column.",
    )
    sampleValues = serializers.ListField(
        child=JSONValueField(), required=False, max_length=10, help_text="Up to 10 sample values from the column."
    )


class SQLChartSpecRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=100000, help_text="The SQL query that produced the results.")
    prompt = serializers.CharField(
        max_length=4000, allow_blank=True, help_text="User instructions for the chart to generate."
    )
    columns = SQLChartColumnSerializer(many=True, help_text="Per-column result shape.")
    sampleRows = serializers.ListField(
        child=serializers.DictField(child=JSONValueField()),
        required=False,
        max_length=20,
        help_text="Up to 20 sample rows keyed by column name.",
    )
    rowCount = serializers.IntegerField(min_value=0, help_text="Total rows returned by the query.")

    def validate_columns(self, columns: list[dict[str, object]]) -> list[dict[str, object]]:
        if not columns:
            raise serializers.ValidationError("At least one column is required.")
        if len(columns) > 100:
            raise serializers.ValidationError("At most 100 columns can be sent.")
        return columns


class SQLChartSpecResponseSerializer(serializers.Serializer):
    mapping = serializers.JSONField(help_text="The generated ChartSpec mapping (columns mapped to chart roles).")
    trace_id = serializers.CharField(help_text="Trace ID for the generation request.")
    warnings = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="Warnings about the generated chart."
    )


class SQLChartSpecViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer

    @validated_request(
        request_serializer=SQLChartSpecRequestSerializer,
        responses={
            200: OpenApiResponse(response=SQLChartSpecResponseSerializer),
            400: OpenApiResponse(description="Invalid request"),
        },
        summary="Generate a quill chart mapping for SQL results",
        description=(
            "Maps SQL result columns to a quill ChartSpec. The frontend combines the mapping with the "
            "actual result rows to render an inline chart — no executable spec is returned."
        ),
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        trace_id = f"sql_chart_spec_{uuid.uuid4()}"
        user = cast(User, request.user)
        payload = cast(SQLChartSpecPayload, request.validated_data)

        warnings: list[str] = []
        try:
            generator = SQLChartSpecGenerator(team=self.team, user=user)
            mapping = async_to_sync(generator.agenerate)(payload)
        except Exception:
            logger.warning("sql_chart_spec.generation_failed", team_id=self.team.id, trace_id=trace_id, exc_info=True)
            mapping = build_fallback_chart_mapping(payload)
            warnings.append("AI generation failed, so a basic chart was generated from the result shape.")

        return Response({"mapping": mapping.model_dump(exclude_none=True), "trace_id": trace_id, "warnings": warnings})
