"""Batch export backfill endpoints: create, list, retrieve and cancel."""

import dataclasses
from typing import Any
from uuid import UUID

import structlog
import posthoganalytics
from drf_spectacular.utils import extend_schema_field
from rest_framework import filters, mixins, request, response, serializers, status, viewsets
from rest_framework.exceptions import APIException, NotFound, ValidationError

from posthog.api.pagination import FacadeCursorPagination, facade_cursor_page_response
from posthog.api.routing import PathParameter, TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.event_usage import groups
from posthog.models import User
from posthog.models.integer_field_bounds import BIG_INTEGER_FIELD_MAX, BIG_INTEGER_FIELD_MIN

from products.batch_exports.backend.facade import (
    api as batch_exports_api,
    contracts,
)
from products.batch_exports.backend.facade.enums import BatchExportBackfillStatus

logger = structlog.get_logger(__name__)


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
        min_value=BIG_INTEGER_FIELD_MIN,
        max_value=BIG_INTEGER_FIELD_MAX,
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


class BatchExportBackfillViewSet(TeamAndOrgViewSetMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """ViewSet for BatchExportBackfill models.

    Allows creating and reading backfills, but not updating or deleting them.
    """

    path_parameters = {
        "pk": PathParameter(type=UUID, description="A UUID string identifying this batch export backfill."),
        "batch_export_id": PathParameter(type=UUID, description="The BatchExport this backfill belongs to."),
    }
    scope_object = "batch_export"
    # batch_export is not an access-control resource, so no rule names one backfill.
    records_have_object_access_rules = False
    serializer_class = BatchExportBackfillSerializer
    pagination_class = BackfillsCursorPagination
    # The paginator reads the ordering through this filter, and the facade applies it.
    filter_backends = [filters.OrderingFilter]
    ordering_fields = list(contracts.BATCH_EXPORT_BACKFILL_ORDERING_FIELDS)
    ordering = "-created_at"

    def _get_export_id(self) -> UUID:
        return self.kwargs["parent_lookup_batch_export_id"]

    def read_object(self) -> contracts.BatchExportBackfillDetail:
        try:
            return batch_exports_api.get_batch_export_backfill(self.team_id, self._get_export_id(), self.kwargs["pk"])
        except contracts.BatchExportBackfillNotFoundError as e:
            raise NotFound(*e.args) from e

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        export_id = self._get_export_id()
        return facade_cursor_page_response(
            self,
            lambda page: batch_exports_api.list_batch_export_backfills(self.team_id, export_id, page=page),
        )

    def create(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Create a new backfill for a BatchExport."""
        export_id = self._get_export_id()
        start_at = request.data.get("start_at")
        end_at = request.data.get("end_at")

        try:
            backfill = batch_exports_api.create_batch_export_backfill(
                self.team_id, export_id, start_at=start_at, end_at=end_at
            )
        except contracts.BatchExportNotFoundError as e:
            raise NotFound("BatchExport not found.") from e
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
