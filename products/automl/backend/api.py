"""DRF views for the AutoML S3 browser.

The product writes everything to S3, so these endpoints are read-only listers
over a fixed prefix. The S3 layout is global (not team-scoped), so the viewset
is registered at the org-wide router level and only requires authentication.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from . import storage
from .serializers import (
    ParquetPreviewSerializer,
    QueryTextSerializer,
    RunDetailSerializer,
    TaskDetailSerializer,
    TaskSummarySerializer,
)

MAX_PARQUET_PREVIEW_ROWS = 200
DEFAULT_PARQUET_PREVIEW_ROWS = 50


@extend_schema(tags=["automl"])
class AutoMLTaskViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    lookup_field = "name"
    lookup_value_regex = r"[A-Za-z0-9_\-]+"

    @extend_schema(responses={200: TaskSummarySerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        tasks = storage.list_tasks()
        return Response(TaskSummarySerializer([t.__dict__ for t in tasks], many=True).data)

    @extend_schema(responses={200: TaskDetailSerializer})
    def retrieve(self, request: Request, name: str, **kwargs) -> Response:
        detail = storage.get_task(name)
        if detail is None:
            raise exceptions.NotFound()
        payload = {
            **detail.__dict__,
            "runs": [r.__dict__ for r in detail.runs],
        }
        return Response(TaskDetailSerializer(payload).data)

    @extend_schema(
        parameters=[OpenApiParameter(name="version", description="Query filename like `v2.sql`.", required=True)],
        responses={200: QueryTextSerializer},
    )
    @action(detail=True, methods=["get"], url_path=r"queries/(?P<version>[A-Za-z0-9_\-.]+)")
    def query(self, request: Request, name: str, version: str, **kwargs) -> Response:
        sql = storage.get_query(name, version)
        if sql is None:
            raise exceptions.NotFound()
        return Response(QueryTextSerializer({"task_name": name, "version": version, "sql": sql}).data)

    @extend_schema(responses={200: RunDetailSerializer})
    @action(detail=True, methods=["get"], url_path=r"runs/(?P<run_id>[A-Za-z0-9_\-:.+]+)")
    def run(self, request: Request, name: str, run_id: str, **kwargs) -> Response:
        run = storage.get_run(name, run_id)
        if run is None:
            raise exceptions.NotFound()
        return Response(RunDetailSerializer(run.__dict__).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(name="artifact", description="Parquet path under the run, e.g. `predictions.parquet`."),
            OpenApiParameter(name="limit", description=f"Page size (max {MAX_PARQUET_PREVIEW_ROWS})."),
            OpenApiParameter(name="offset", description="Zero-based row offset for paging."),
        ],
        responses={200: ParquetPreviewSerializer},
    )
    @action(
        detail=True,
        methods=["get"],
        url_path=r"runs/(?P<run_id>[A-Za-z0-9_\-:.+]+)/preview",
    )
    def preview(self, request: Request, name: str, run_id: str, **kwargs) -> Response:
        artifact = request.query_params.get("artifact", "predictions.parquet")
        limit = _parse_limit(request.query_params.get("limit"))
        offset = _parse_offset(request.query_params.get("offset"))
        preview = storage.preview_parquet(name, run_id, artifact, limit=limit, offset=offset)
        if preview is None:
            raise exceptions.NotFound()
        return Response(ParquetPreviewSerializer(preview).data)


def _parse_limit(raw: str | None) -> int:
    if raw is None:
        return DEFAULT_PARQUET_PREVIEW_ROWS
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PARQUET_PREVIEW_ROWS
    return max(1, min(parsed, MAX_PARQUET_PREVIEW_ROWS))


def _parse_offset(raw: str | None) -> int:
    if raw is None:
        return 0
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)
