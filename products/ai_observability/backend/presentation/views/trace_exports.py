from collections.abc import Mapping
from functools import partial
from typing import Any

from django.db import models, transaction
from django.http import HttpResponseBase
from django.urls import reverse

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import PARENT_LOOKUP_KWARG_PREFIX
from posthog.event_usage import report_user_action
from posthog.helpers.impersonation import is_impersonated
from posthog.rate_limit import _UserBucketRateThrottle

from products.exports.backend.facade.api import get_export_asset, get_export_asset_content_response

from ...facade import api, contracts
from .trace_ids import MalformedTraceIdSegmentError, decode_trace_id_segment, encode_trace_id_segment
from .trace_resource import TRACE_ID_PARAMETER, TRACE_LOOKUP, TraceQuerySerializer, TraceResourceViewSet, request_user

EXPORT_ID_PARAMETER = OpenApiParameter(
    "export_id", OpenApiTypes.INT, OpenApiParameter.PATH, description="The export id the create call returned."
)
EXPORT_NOT_FOUND_RESPONSE = OpenApiResponse(description="You have no export with this id for this trace.")


class TraceExportRateThrottle(_UserBucketRateThrottle):
    scope = "ai_trace_export"
    rate = "20/hour"


# Gives the export request body its own schema, apart from the trace read's query parameters.
class TraceExportCreateSerializer(TraceQuerySerializer):
    pass


class TraceExportErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the file cannot be downloaded yet.")


class TraceExportContentPurpose(models.TextChoices):
    DOWNLOAD = "download", "Download"
    COPY = "copy", "Copy"


class TraceExportContentQuerySerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(
        choices=TraceExportContentPurpose.choices,
        default=TraceExportContentPurpose.DOWNLOAD,
        help_text="What the file is read for. Only a download is recorded as one.",
    )


class TraceExportViewSet(TraceResourceViewSet):
    scope_object_read_actions = ["create", "retrieve", "content"]
    lookup_url_kwarg = "export_id"
    lookup_value_regex = r"\d+"

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action == "create":
            return [TraceExportRateThrottle()]
        return super().get_throttles()

    @validated_request(
        request_serializer=TraceExportCreateSerializer,
        parameters=[TRACE_ID_PARAMETER],
        responses={
            201: OpenApiResponse(response=contracts.TraceExport),
            400: OpenApiResponse(description="The timestamp hint or the encoded trace id is malformed."),
            429: OpenApiResponse(description="Too many exports were requested."),
        },
        operation_id="ai_observability_traces_exports_create",
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Starts writing the trace and every node, inputs and outputs included, to a JSON file. Poll the export until it completes, then download it."""
        try:
            trace_id = decode_trace_id_segment(self.trace_segment)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        export = api.create_trace_export(
            self.team,
            request_user(request),
            trace_id,
            request.validated_data.get("timestamp_hint"),
            was_impersonated=is_impersonated(request),
        )
        return Response(export.model_dump(mode="json", by_alias=True), status=status.HTTP_201_CREATED)

    @validated_request(
        parameters=[TRACE_ID_PARAMETER, EXPORT_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceExport),
            400: OpenApiResponse(description="The encoded trace id is malformed."),
            404: EXPORT_NOT_FOUND_RESPONSE,
        },
        operation_id="ai_observability_traces_exports_retrieve",
    )
    def retrieve(self, request: ValidatedRequest, export_id: str, **kwargs: Any) -> Response:
        """The state of one of your exports of this trace."""
        try:
            export = self._trace_export(request, export_id)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        except api.TraceExportNotFoundError:
            return Response({"detail": "Export not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(export.model_dump(mode="json", by_alias=True))

    @extend_schema(
        parameters=[TRACE_ID_PARAMETER, EXPORT_ID_PARAMETER, TraceExportContentQuerySerializer],
        responses={
            (200, "application/json"): OpenApiResponse(response=contracts.TraceExportFile),
            400: OpenApiResponse(description="The encoded trace id or the purpose is malformed."),
            404: EXPORT_NOT_FOUND_RESPONSE,
            409: OpenApiResponse(
                response=TraceExportErrorSerializer, description="The export is still being written, or failed."
            ),
        },
        operation_id="ai_observability_traces_exports_content_retrieve",
    )
    @action(detail=True, methods=["GET"])
    def content(self, request: Request, export_id: str, **kwargs: Any) -> HttpResponseBase:
        """Downloads a completed export as a JSON file."""
        query = TraceExportContentQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            export = self._trace_export(request, export_id)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        except api.TraceExportNotFoundError:
            return Response({"detail": "Export not found."}, status=status.HTTP_404_NOT_FOUND)
        asset = get_export_asset(team_id=self.team.pk, asset_id=export.id)
        if export.status != "complete" or asset is None:
            detail = export.exception or "The export is still being prepared."
            return Response({"detail": detail}, status=status.HTTP_409_CONFLICT)
        response = get_export_asset_content_response(asset=asset, download=True)
        if query.validated_data["purpose"] == TraceExportContentPurpose.COPY:
            return response
        transaction.on_commit(
            partial(
                report_user_action,
                request.user,
                "llma trace export downloaded",
                {"export_id": export.id},
                team=self.team,
                request=request,
            ),
            robust=True,
        )
        return response

    def _trace_export(self, request: Request, export_id: str) -> contracts.TraceExport:
        return api.get_trace_export(
            self.team, request_user(request), decode_trace_id_segment(self.trace_segment), int(export_id)
        )


def trace_export_content_path(*, team_id: int, asset_id: int, export_context: Mapping[str, object]) -> str | None:
    trace_id = api.exported_trace_id(export_context)
    if trace_id is None:
        return None
    return reverse(
        "project_ai_observability_trace_exports-content",
        kwargs={
            f"{PARENT_LOOKUP_KWARG_PREFIX}team_id": team_id,
            f"{PARENT_LOOKUP_KWARG_PREFIX}{TRACE_LOOKUP}": encode_trace_id_segment(trace_id),
            "export_id": asset_id,
        },
    )
