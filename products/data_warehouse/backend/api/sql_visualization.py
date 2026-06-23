import uuid
from typing import cast

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema_field
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User

from products.data_warehouse.backend.sql_visualization_ai import (
    SQLVisualizationGenerationPayload,
    generate_sql_visualization,
)

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

JSON_OBJECT_SCHEMA = {"type": "object", "additionalProperties": True}

logger = structlog.get_logger(__name__)


@extend_schema_field(JSON_VALUE_SCHEMA)
class JSONValueField(serializers.JSONField):
    pass


@extend_schema_field(JSON_OBJECT_SCHEMA)
class JSONObjectField(serializers.JSONField):
    def to_internal_value(self, data: object) -> dict[str, object]:
        value = super().to_internal_value(data)
        if not isinstance(value, dict):
            raise serializers.ValidationError("Expected a JSON object.")
        return cast(dict[str, object], value)


class SQLVisualizationColumnSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=256,
        help_text="Original SQL result column name.",
    )
    type = serializers.CharField(
        max_length=128,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Database result type for the column, when known.",
    )
    semanticType = serializers.ChoiceField(
        choices=["temporal", "quantitative", "nominal", "ordinal"],
        required=False,
        help_text="Best-effort Vega-Lite semantic type inferred from the column type and sample values.",
    )
    sampleValues = serializers.ListField(
        child=JSONValueField(help_text="A compact sample value from this column."),
        max_length=10,
        help_text="Up to 10 compact, distinct sample values from this column.",
    )
    nullCount = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="Number of sampled rows where this column was null.",
    )
    distinctSampleCount = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="Number of distinct values found in the sample for this column.",
    )


class SQLVisualizationFieldSerializer(serializers.Serializer):
    field = serializers.CharField(
        max_length=128,
        help_text="Stable field name the Vega-Lite spec must reference.",
    )
    sourceColumn = serializers.CharField(
        max_length=256,
        help_text="Original SQL result column name.",
    )
    label = serializers.CharField(
        max_length=256,
        help_text="Human-readable display label for the field.",
    )
    type = serializers.CharField(
        max_length=128,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Database result type for the source column, when known.",
    )
    semanticType = serializers.ChoiceField(
        choices=["temporal", "quantitative", "nominal", "ordinal"],
        required=False,
        help_text="Best-effort Vega-Lite semantic type inferred for this field.",
    )


class SQLVisualizationViewSerializer(serializers.Serializer):
    width = serializers.IntegerField(
        min_value=120,
        max_value=2000,
        help_text="Approximate visualization pane width in CSS pixels.",
    )
    height = serializers.IntegerField(
        min_value=120,
        max_value=2000,
        help_text="Approximate visualization pane height in CSS pixels.",
    )


class SQLVisualizationGenerationRequestSerializer(serializers.Serializer):
    query = serializers.CharField(
        max_length=100000,
        help_text="The SQL query that produced the result being visualized.",
    )
    prompt = serializers.CharField(
        max_length=4000,
        help_text="User-editable visualization instructions for the AI generator.",
    )
    columns = SQLVisualizationColumnSerializer(
        many=True,
        help_text="Compact per-column result shape, including types and sample values.",
    )
    fields = SQLVisualizationFieldSerializer(
        many=True,
        required=False,
        help_text="Stable Vega field aliases. When present, generated specs must reference these field names.",
    )
    sampleRows = serializers.ListField(
        child=serializers.DictField(
            child=JSONValueField(help_text="A compact sampled cell value keyed by Vega field alias.")
        ),
        max_length=20,
        help_text="Up to 20 compact sample rows keyed by Vega field alias.",
    )
    rowCount = serializers.IntegerField(
        min_value=0,
        help_text="Total number of rows returned by the SQL query.",
    )
    view = SQLVisualizationViewSerializer(
        required=False,
        help_text="Approximate visualization pane dimensions for choosing chart layout.",
    )

    def validate_columns(self, columns: list[dict[str, object]]) -> list[dict[str, object]]:
        if len(columns) == 0:
            raise serializers.ValidationError("At least one column is required.")
        if len(columns) > 100:
            raise serializers.ValidationError("At most 100 columns can be sent.")
        return columns

    def validate_fields(self, fields: list[dict[str, object]] | None) -> list[dict[str, object]] | None:
        if fields is not None and len(fields) > 100:
            raise serializers.ValidationError("At most 100 field aliases can be sent.")
        return fields


class SQLVisualizationGenerationResponseSerializer(serializers.Serializer):
    spec = JSONObjectField(help_text="Generated Vega-Lite JSON specification.")
    trace_id = serializers.CharField(help_text="Trace ID for the AI generation request.")
    explanation = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Short explanation of the generated visualization.",
    )
    warnings = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Warnings about limitations in the generated visualization.",
    )


class SQLVisualizationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer

    @validated_request(
        request_serializer=SQLVisualizationGenerationRequestSerializer,
        responses={
            200: OpenApiResponse(response=SQLVisualizationGenerationResponseSerializer),
            400: OpenApiResponse(description="Invalid request"),
            500: OpenApiResponse(description="Failed to generate visualization"),
        },
        summary="Generate a Vega-Lite visualization for SQL results",
        description=(
            "Generates a Vega-Lite JSON specification from a compact SQL result shape. "
            "The returned spec must be validated client-side before rendering."
        ),
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        trace_id = f"sql_visualization_{uuid.uuid4()}"
        user = cast(User, request.user)
        payload = cast(SQLVisualizationGenerationPayload, request.validated_data)

        try:
            result = generate_sql_visualization(payload=payload, team=self.team, user=user, trace_id=trace_id)
        except Exception:
            logger.warning(
                "sql_visualization.generation_failed",
                team_id=self.team.id,
                trace_id=trace_id,
                exc_info=True,
            )
            return Response(
                {"detail": "Could not generate a visualization for these results."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "spec": result.spec,
                "trace_id": trace_id,
                "explanation": result.explanation,
                "warnings": result.warnings,
            },
            status=status.HTTP_200_OK,
        )
