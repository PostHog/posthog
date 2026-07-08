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

from products.data_warehouse.backend.sql_flint_spec_ai import SQLFlintSpecGenerator, SQLFlintSpecPayload

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


class SQLFlintColumnSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=256, help_text="Result column name.")
    type = serializers.CharField(
        max_length=128, required=False, allow_null=True, allow_blank=True, help_text="Database column type, if known."
    )
    sampleValues = serializers.ListField(
        child=JSONValueField(), required=False, max_length=10, help_text="Up to 10 sample values from the column."
    )


class SQLFlintSpecRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=100000, help_text="The SQL query that produced the results.")
    prompt = serializers.CharField(
        max_length=4000, allow_blank=True, help_text="User instructions for the chart to generate."
    )
    columns = SQLFlintColumnSerializer(many=True, help_text="Per-column result shape.")
    rowCount = serializers.IntegerField(min_value=0, help_text="Total rows returned by the query.")

    def validate_columns(self, columns: list[dict[str, object]]) -> list[dict[str, object]]:
        if not columns:
            raise serializers.ValidationError("At least one column is required.")
        if len(columns) > 100:
            raise serializers.ValidationError("At most 100 columns can be sent.")
        return columns


class SQLFlintSpecResponseSerializer(serializers.Serializer):
    chart_spec = serializers.JSONField(
        allow_null=True,
        help_text="The generated Flint chart spec (chartType + channel encodings), or null when generation failed.",
    )
    semantic_types = serializers.DictField(
        child=serializers.CharField(),
        required=False,
        help_text="Per-column Flint semantic type annotations for the spec.",
    )
    narrative = serializers.CharField(
        required=False, allow_null=True, help_text="One-sentence description of the chart's takeaway."
    )
    trace_id = serializers.CharField(help_text="Trace ID for the generation request.")
    warnings = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="Warnings about the generated chart."
    )


class SQLFlintSpecViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer

    @validated_request(
        request_serializer=SQLFlintSpecRequestSerializer,
        responses={
            200: OpenApiResponse(response=SQLFlintSpecResponseSerializer),
            400: OpenApiResponse(description="Invalid request"),
        },
        summary="Generate a Flint chart spec for SQL results",
        description=(
            "Maps SQL result columns to a compact Flint chart spec (chart type + channel encodings + "
            "semantic types). The frontend compiles the spec with the actual result rows through the "
            "flint-chart quill backend — no executable spec and no result data leave the client."
        ),
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        trace_id = f"sql_flint_spec_{uuid.uuid4()}"
        user = cast(User, request.user)
        payload = cast(SQLFlintSpecPayload, request.validated_data)

        try:
            generator = SQLFlintSpecGenerator(team=self.team, user=user)
            spec = async_to_sync(generator.agenerate)(payload)
        except Exception:
            logger.warning("sql_flint_spec.generation_failed", team_id=self.team.id, trace_id=trace_id, exc_info=True)
            return Response(
                {
                    "chart_spec": None,
                    "trace_id": trace_id,
                    "warnings": ["AI generation failed — showing the chart inferred from the result shape instead."],
                }
            )

        return Response(
            {
                "chart_spec": {
                    "chartType": spec.chartType,
                    "encodings": spec.encodings.model_dump(exclude_none=True),
                },
                "semantic_types": spec.semantic_types,
                "narrative": spec.narrative,
                "trace_id": trace_id,
                "warnings": [],
            }
        )
