"""Batch export backfill endpoints: create, list, retrieve and cancel."""

import uuid
import dataclasses
from typing import Any, cast

import structlog
import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import filters, request, response, serializers, status, viewsets
from rest_framework.exceptions import APIException, NotFound, ValidationError

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.event_usage import groups
from posthog.models import User

from products.batch_exports.backend.facade import (
    api as batch_exports_api,
    contracts,
)
from products.batch_exports.backend.facade.enums import BatchExportBackfillStatus
from products.batch_exports.backend.presentation.views.batch_export.pagination import FacadeCursorPagination
from products.batch_exports.backend.presentation.views.utils import BIG_INTEGER_MAX, BIG_INTEGER_MIN, parse_path_uuid

logger = structlog.get_logger(__name__)

BATCH_EXPORT_NOT_FOUND = "BatchExport not found."

# The viewset declares no queryset, so drf-spectacular cannot read the type of the ids from a model.
BATCH_EXPORT_ID_PARAMETER = OpenApiParameter(
    "batch_export_id",
    {"type": "string", "format": "uuid", "description": "The BatchExport this backfill belongs to."},
    OpenApiParameter.PATH,
)
BACKFILL_ID_PARAMETER = OpenApiParameter(
    "id",
    OpenApiTypes.UUID,
    OpenApiParameter.PATH,
    description="A UUID string identifying this batch export backfill.",
)


class BatchExportBackfillSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    progress = serializers.SerializerMethodField(read_only=True)
    start_at = serializers.DateTimeField(required=False, allow_null=True, help_text="The start of the data interval.")
    end_at = serializers.DateTimeField(required=False, allow_null=True, help_text="The end of the data interval.")
    status = serializers.ChoiceField(
        choices=BatchExportBackfillStatus.choices, help_text="The status of this backfill."
    )
    created_at = serializers.DateTimeField(
        read_only=True, help_text="The timestamp at which this BatchExportBackfill was created."
    )
    finished_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="The timestamp at which this BatchExportBackfill finished, successfully or not.",
    )
    last_updated_at = serializers.DateTimeField(
        read_only=True, help_text="The timestamp at which this BatchExportBackfill was last updated."
    )
    total_records_count = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=BIG_INTEGER_MIN,
        max_value=BIG_INTEGER_MAX,
        help_text="The total number of records to export. Initially estimated, updated with actual count after completion.",
    )
    adjusted_start_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="The actual start time after adjustment for earliest available data. May differ from start_at if user requested a date before data exists.",
    )
    team = serializers.IntegerField(source="team_id", help_text="The team this belongs to.")
    batch_export = serializers.UUIDField(
        source="batch_export_id", help_text="The BatchExport this backfill belongs to."
    )

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "properties": {
                "total_runs": {"type": "integer", "nullable": True},
                "finished_runs": {"type": "integer", "nullable": True},
                "progress": {"type": "number", "nullable": True},
            },
        }
    )
    def get_progress(self, obj: contracts.BatchExportBackfillDetail) -> dict[str, Any] | None:
        """Return progress information containing total runs, finished runs, and progress percentage."""
        if obj.progress is None:
            return None
        return dataclasses.asdict(obj.progress)


class BackfillsCursorPagination(FacadeCursorPagination):
    page_size = 50


class TooManyConcurrentBackfills(APIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "too_many_concurrent_backfills"
    default_detail = "Too many concurrent batch export backfills for this team."


@extend_schema(parameters=[BATCH_EXPORT_ID_PARAMETER])
class BatchExportBackfillViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """ViewSet for BatchExportBackfill models.

    Allows creating and reading backfills, but not updating or deleting them.
    """

    scope_object = "batch_export"
    serializer_class = BatchExportBackfillSerializer
    pagination_class = BackfillsCursorPagination
    # The paginator reads the ordering through this filter, and the facade applies it.
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at", "start_at"]
    ordering = "-created_at"

    def _get_export_id(self, detail: str | None = None) -> uuid.UUID:
        return parse_path_uuid(self.kwargs["parent_lookup_batch_export_id"], detail)

    def dangerously_get_object(self) -> contracts.BatchExportBackfillDetail:
        # This replaces the queryset read only. The facade scopes the read to the team and the
        # export, and the object permissions run on the contract as they ran on the model.
        try:
            backfill = batch_exports_api.get_batch_export_backfill(
                self.team_id, self._get_export_id(), parse_path_uuid(self.kwargs["pk"])
            )
        except contracts.BatchExportBackfillNotFoundError as e:
            raise NotFound(*e.args) from e
        self.check_object_permissions(self.request, backfill)
        return backfill

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        export_id = self._get_export_id()
        paginator = cast(BackfillsCursorPagination, self.paginator)
        backfills = paginator.paginate_facade(
            request,
            self,
            lambda page: batch_exports_api.list_batch_export_backfills(self.team_id, export_id, page=page),
        )
        return paginator.get_paginated_response(self.get_serializer(backfills, many=True).data)

    @extend_schema(parameters=[BACKFILL_ID_PARAMETER])
    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        return response.Response(self.get_serializer(self.get_object()).data)

    def create(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Create a new backfill for a BatchExport."""
        export_id = self._get_export_id(BATCH_EXPORT_NOT_FOUND)
        start_at = request.data.get("start_at")
        end_at = request.data.get("end_at")

        try:
            backfill = batch_exports_api.create_batch_export_backfill(
                self.team_id, export_id, start_at=start_at, end_at=end_at
            )
        except contracts.BatchExportNotFoundError as e:
            raise NotFound(BATCH_EXPORT_NOT_FOUND) from e
        except contracts.InvalidBackfillRequestError as e:
            raise ValidationError(str(e)) from e
        except contracts.TooManyConcurrentBackfillsError as e:
            raise TooManyConcurrentBackfills(str(e)) from e

        if isinstance(request.user, User):
            try:
                posthoganalytics.capture(
                    distinct_id=str(request.user.distinct_id),
                    event="batch export backfill created",
                    properties={
                        "backfill_id": backfill.backfill_id,
                        "batch_export_id": str(export_id),
                        "destination_type": backfill.destination_type,
                        "has_start_at": start_at is not None,
                        "has_end_at": end_at is not None,
                        "team_id": self.team_id,
                    },
                    groups=groups(self.team.organization, self.team),
                )
            except Exception:
                logger.exception("Failed to capture batch export backfill created event")

        return response.Response({"backfill_id": backfill.backfill_id}, status=status.HTTP_201_CREATED)

    @extend_schema(parameters=[BACKFILL_ID_PARAMETER])
    @action(methods=["POST"], detail=True, required_scopes=["batch_export:write"])
    def cancel(self, *args, **kwargs) -> response.Response:
        """Cancel a batch export backfill."""
        backfill = self.get_object()

        try:
            batch_exports_api.cancel_batch_export_backfill(self.team_id, self._get_export_id(), backfill.id)
        except contracts.InvalidBackfillRequestError as e:
            raise ValidationError(str(e)) from e
        except contracts.BatchExportBackfillNotFoundError as e:
            raise NotFound(*e.args) from e

        return response.Response({"cancelled": True})
