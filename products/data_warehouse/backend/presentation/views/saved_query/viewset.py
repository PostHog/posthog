"""The saved-query viewset and the request bodies of its actions."""

from dataclasses import dataclass
from typing import Any, cast

from django.db.models import Model, OuterRef, Prefetch, Subquery, TextField
from django.db.models.functions import Cast

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, filters, request, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from posthog.hogql.database.database import Database

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions_capture import capture_exception
from posthog.helpers.impersonation import is_impersonated
from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog, Change, Detail, load_activity, log_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.rate_limit import MaterializationRateThrottle, RunSavedQueryRateThrottle
from posthog.rbac.query_access import assert_user_can_read_query
from posthog.temporal.common.client import sync_connect

from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin
from products.data_modeling.backend.facade.models import DataModelingJob, DataModelingJobEngine, DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.models import sync_frequency_to_sync_frequency_interval

from . import editing, incremental_config, lifecycle, lineage, sync_cadence, view_state

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class _CancelTarget:
    workflow_id: str
    workflow_run_id: str | None


class DataWarehouseSavedQueryPagination(PageNumberPagination):
    page_size = 1000


class SavedQueryResumeSerializer(serializers.Serializer):
    resumed = serializers.BooleanField(help_text="False when the query's materialization was not suspended.")


class SavedQueryResumeSchedulesRequestSerializer(serializers.Serializer):
    """Body of the `resume_schedules` action."""

    view_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        help_text=(
            "Ids of the saved queries to resume. An id is ignored when it is not in this project, "
            "has been deleted, or you cannot edit it."
        ),
    )


class SavedQueryRunSerializer(serializers.Serializer):
    """Body of the `run` action."""

    full_refresh = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Rebuild the whole table instead of updating it incrementally. Has no effect on a "
        "view that is not incremental. This is how you reprocess history after changing what the "
        "query means without changing its text, or after upstream data was corrected.",
    )


class SavedQueryMaterializeSerializer(serializers.Serializer):
    """Body of the `materialize` action: which cadence to enable materialization at."""

    sync_frequency = sync_cadence.SyncFrequencyField(
        choices=sync_cadence.MATERIALIZE_SYNC_FREQUENCY_CHOICES,
        allow_null=False,
        default=sync_cadence.DEFAULT_MATERIALIZE_SYNC_FREQUENCY,
        help_text=(
            "How often to refresh the materialized table, defaulting to daily. Rejected with a 400 when it falls "
            "outside what the query's lineage allows: no more often than its sources deliver new data, and no less "
            "often than a downstream view or endpoint needs."
        ),
    )


class DataWarehouseSavedQueryViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete Warehouse Tables.
    """

    scope_object = "warehouse_view"
    queryset = DataWarehouseSavedQuery.objects.all()
    serializer_class = editing.DataWarehouseSavedQuerySerializer
    pagination_class = DataWarehouseSavedQueryPagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    ordering = "-created_at"

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        request_data = getattr(self.request, "data", {})
        should_include_database = self.action in {"create", "list", "retrieve"} or (
            self.action in {"update", "partial_update"} and ("name" in request_data or "query" in request_data)
        )

        if should_include_database:
            context["database"] = Database.create_for(team_id=self.team_id, user=cast(User, self.request.user))
        return context

    def get_serializer_class(self):
        if self.action == "list":
            return view_state.DataWarehouseSavedQueryMinimalSerializer
        return editing.DataWarehouseSavedQuerySerializer

    def safely_get_queryset(self, queryset):
        base_queryset = (
            queryset.prefetch_related(
                "created_by",
                "managed_viewset",
                "column_annotations",
                Prefetch(
                    "datamodelingjob_set",
                    queryset=DataModelingJob.objects.exclude(engine=DataModelingJobEngine.DUCKGRES).order_by(
                        "-last_run_at"
                    )[:1],
                    to_attr="jobs",
                ),
            )
            .exclude(deleted=True)
            .order_by(self.ordering)
        )

        # Hide endpoint-origin saved queries from the list view — they belong to the endpoints UI.
        # Allow retrieve so the Node detail page can fetch them by ID.
        if self.action == "list":
            base_queryset = base_queryset.exclude(origin=DataWarehouseSavedQuery.Origin.ENDPOINT)

        # Detect whether we should include managed views in the queryset
        is_managed_viewset_enabled = posthoganalytics.feature_enabled(
            "managed-viewsets",
            str(self.team.uuid),
            groups={
                "organization": str(self.team.organization_id),
                "project": str(self.team.id),
            },
            group_properties={
                "organization": {
                    "id": str(self.team.organization_id),
                },
                "project": {
                    "id": str(self.team.id),
                },
            },
            send_feature_flag_events=False,
        )

        if not is_managed_viewset_enabled:
            base_queryset = base_queryset.filter(managed_viewset__isnull=True)

        # Only annotate with latest activity ID for list operations, not for single object retrieves
        # This avoids the annotation when we're getting a single object for update/create/etc.
        action = self.action if hasattr(self, "action") else None
        if action == "list" or action == "retrieve":
            # Add latest query-changing activity id annotation to avoid N+1 queries. Scoped to query
            # edits (see QUERY_CHANGE_ACTIVITY_FILTER) so materialization syncs don't advance the head.
            latest_activity = (
                ActivityLog.objects.filter(
                    scope="DataWarehouseSavedQuery",
                    item_id=Cast(OuterRef("id"), output_field=TextField()),
                    team_id=self.team_id,
                    **editing.QUERY_CHANGE_ACTIVITY_FILTER,
                )
                .order_by("-created_at")
                .values("id")[:1]
            )

            return base_queryset.annotate(latest_activity_id=Subquery(latest_activity))

        return base_queryset

    def create(self, request, *args, **kwargs):
        # Check for UPSERT logic
        saved_query = DataWarehouseSavedQuery.objects.filter(
            team_id=self.team_id, name=request.data.get("name")
        ).first()
        if saved_query:
            # The UPSERT branch updates an existing row without going through get_object(),
            # so run object-level permission checks explicitly to honor per-object access controls.
            self.check_object_permissions(request, saved_query)
            serializer = self.get_serializer(saved_query, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            # Create logic
            self.perform_create(serializer)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

    def destroy(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        from products.data_modeling.backend.facade.api import HasDependentsError

        instance: DataWarehouseSavedQuery = self.get_object()
        name = instance.name
        try:
            lifecycle.delete_saved_query(instance)
        except HasDependentsError:
            raise serializers.ValidationError(
                "Cannot delete this view because other views depend on it. Delete or update those views first."
            )

        log_activity(
            organization_id=self.team.organization_id,
            team_id=self.team_id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
            item_id=instance.id,
            scope="DataWarehouseSavedQuery",
            activity="deleted",
            detail=Detail(name=name),
        )

        return response.Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=SavedQueryRunSerializer, responses={200: None})
    @action(
        methods=["POST"],
        detail=True,
        required_scopes=["warehouse_view:write"],
        throttle_classes=[RunSavedQueryRateThrottle],
    )
    def run(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Run this saved query."""
        from products.data_modeling.backend.facade.api import (
            MissingDagNodeError,
            clear_incremental_state,
            materialize_saved_query,
        )

        body = SavedQueryRunSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        saved_query = self.get_object()

        if body.validated_data["full_refresh"]:
            # Dropping the watermark is the whole mechanism: the next run finds no progress to
            # build on and rebuilds. Commit it before dispatch, and outside any transaction the
            # dispatch could roll back, or the worker reads the old watermark and runs
            # incrementally instead.
            clear_incremental_state(saved_query)

        try:
            materialize_saved_query(saved_query, triggered_by_id=request.user.pk)
        except MissingDagNodeError:
            raise exceptions.ValidationError(
                detail="This view isn't fully set up to materialize. Save the query again, then try syncing."
            )

        log_activity(
            organization_id=self.team.organization_id,
            team_id=self.team_id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
            item_id=saved_query.id,
            scope="DataWarehouseSavedQuery",
            activity="sync_triggered",
            detail=Detail(name=saved_query.name),
        )

        return response.Response(status=status.HTTP_200_OK)

    @extend_schema(
        request=incremental_config.CheckIncrementalSerializer,
        responses={200: incremental_config.IncrementalEligibilitySerializer},
    )
    @action(
        methods=["POST"],
        detail=False,
        required_scopes=["warehouse_view:read"],
        throttle_classes=[incremental_config.CheckIncrementalThrottle],
    )
    def check_incremental(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Report whether a query can be materialized incrementally, without running it.

        Parses the SQL only, so it is cheap enough to call from the editor as the user types. Lets
        the editor explain why the incremental option is unavailable before anything is saved.
        """
        from products.data_modeling.backend.facade.api import IncrementalConfig, check_incremental_eligibility

        body = incremental_config.CheckIncrementalSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data

        config = None
        if data.get("incremental_key") and data.get("unique_key"):
            config = IncrementalConfig(
                incremental_key=data["incremental_key"],
                unique_key=tuple(data["unique_key"]),
                lookback_seconds=data.get("lookback_seconds", 0),
            )

        result = check_incremental_eligibility(
            data["query"],
            config,
            database=Database.create_for(team_id=self.team_id, user=cast(User, request.user)),
        )
        return response.Response(
            incremental_config.IncrementalEligibilitySerializer(
                {
                    "eligible": result.eligible,
                    "key_candidates": result.key_candidates,
                    "unique_key_candidates": result.unique_key_candidates,
                    "key_candidate_types": result.key_candidate_types,
                    "blockers": result.blockers,
                    "warnings": result.warnings,
                }
            ).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(request=None, responses={200: SavedQueryResumeSerializer})
    @action(methods=["POST"], detail=True, required_scopes=["warehouse_view:write"])
    def resume(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Resume materialization suspended after repeated failures.

        Scheduled runs skip a suspended model and everything downstream of it, so it cannot succeed
        its way back on its own.
        """
        from products.data_modeling.backend.facade.api import unsuspend_saved_query

        resumed = unsuspend_saved_query(self.get_object())

        return response.Response({"resumed": bool(resumed)}, status=status.HTTP_200_OK)

    @action(
        methods=["POST"],
        detail=True,
        required_scopes=["warehouse_view:write"],
        throttle_classes=[MaterializationRateThrottle],
    )
    def revert_materialization(self, request: request.Request, *args, **kwargs) -> response.Response:
        """
        Undo materialization, revert back to the original view.
        (i.e. delete the materialized table and the schedule)
        """
        saved_query: DataWarehouseSavedQuery = self.get_object()

        if saved_query.managed_viewset is not None:
            raise serializers.ValidationError("Cannot revert materialization of a query from a managed viewset.")

        saved_query.revert_materialization()

        # set data modeling node type to view
        try:
            from products.data_modeling.backend.facade.api import update_node_type
            from products.data_modeling.backend.facade.models import NodeType

            update_node_type(saved_query, NodeType.VIEW)
        except Exception as e:
            capture_exception(e)
            logger.exception("Failed to update node type to view", saved_query_name=saved_query.name)

        log_activity(
            organization_id=self.team.organization_id,
            team_id=self.team_id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
            item_id=saved_query.id,
            scope="DataWarehouseSavedQuery",
            activity="materialization_disabled",
            detail=Detail(name=saved_query.name),
        )

        return response.Response(status=status.HTTP_200_OK)

    @extend_schema(request=SavedQueryMaterializeSerializer, responses={200: None})
    @action(
        methods=["POST"],
        detail=True,
        required_scopes=["warehouse_view:write"],
        throttle_classes=[MaterializationRateThrottle],
    )
    def materialize(self, request: request.Request, *args, **kwargs) -> response.Response:
        """
        Enable materialization for this saved query, at the requested sync frequency or daily.
        """
        saved_query: DataWarehouseSavedQuery = self.get_object()

        if saved_query.managed_viewset is not None:
            raise serializers.ValidationError("Cannot materialize a query from a managed viewset.")

        assert_user_can_read_query(saved_query.query, self.team_id, cast(User, request.user))

        params = SavedQueryMaterializeSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        sync_frequency_interval = sync_frequency_to_sync_frequency_interval(params.validated_data["sync_frequency"])

        from products.data_modeling.backend.facade.api import (
            UnsatisfiableFrequencyError,
            UnsupportedFrequencyTargetError,
            check_saved_query_frequency_target,
            saved_query_target_bounds,
        )

        if sync_frequency_interval is not None:
            # Ask before writing, so the ordinary refusal never has to be undone below. Names only
            # what this caller may read, matching the bounds payload — otherwise one rejected
            # materialize reads back a node they were never shown.
            bounds = saved_query_target_bounds(self.team_id, saved_query.pk)
            try:
                check_saved_query_frequency_target(
                    saved_query,
                    sync_frequency_interval,
                    visible_names=(
                        sync_cadence.visible_blocker_names(bounds, self.user_access_control, team_id=self.team_id)
                        if bounds
                        else {}
                    ),
                )
            except (UnsatisfiableFrequencyError, UnsupportedFrequencyTargetError) as e:
                raise serializers.ValidationError(str(e))

        previous_interval = saved_query.sync_frequency_interval
        previously_materialized = saved_query.is_materialized

        saved_query.sync_frequency_interval = sync_frequency_interval
        saved_query.is_materialized = True
        saved_query.save(update_fields=["sync_frequency_interval", "is_materialized"])

        # Enable materialization - this handles model path setup and schedule creation
        # If this fails, it will set is_materialized = False
        try:
            saved_query.schedule_materialization(trigger_immediate_run=True, triggered_by_id=request.user.pk)
        except (UnsatisfiableFrequencyError, UnsupportedFrequencyTargetError):
            # The check above already refused every cadence the lineage forbids, so reaching here
            # means the lineage moved mid-request. Say so plainly rather than forwarding a message
            # built from unredacted names. `schedule_materialization` re-raises these without
            # applying its disable-on-failure contract, and this action is not inside an atomic
            # block, so undo the enable by hand: otherwise the 400 leaves is_materialized=True
            # behind and the UI reads the rejection as a success.
            saved_query.sync_frequency_interval = previous_interval
            saved_query.is_materialized = previously_materialized
            saved_query.save(update_fields=["sync_frequency_interval", "is_materialized"])
            raise serializers.ValidationError(
                "This view's lineage changed while we were setting it up. Reopen it and pick a cadence again."
            )

        # Refresh from DB to check if schedule_materialization set is_materialized = False on failure
        saved_query.refresh_from_db()
        if saved_query.is_materialized is False:
            return response.Response(
                {"error": "Materialization failed. Please try again or contact support."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # set data modeling node type to matview
        try:
            from products.data_modeling.backend.facade.api import update_node_type
            from products.data_modeling.backend.facade.models import NodeType

            update_node_type(saved_query, NodeType.MAT_VIEW)
        except Exception as e:
            capture_exception(e)
            logger.exception("Failed to update node type to matview", saved_query_name=saved_query.name)

        log_activity(
            organization_id=self.team.organization_id,
            team_id=self.team_id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
            item_id=saved_query.id,
            scope="DataWarehouseSavedQuery",
            activity="materialization_enabled",
            detail=Detail(
                name=saved_query.name,
                changes=[
                    Change(
                        field="sync_frequency_interval",
                        action="changed",
                        type="DataWarehouseSavedQuery",
                        before=str(previous_interval) if previous_interval else None,
                        after=str(sync_frequency_interval),
                    ),
                ],
            ),
        )

        return response.Response(status=status.HTTP_200_OK)

    @extend_schema(request=SavedQueryResumeSchedulesRequestSerializer, responses={202: None})
    @action(methods=["POST"], detail=False, required_scopes=["warehouse_view:write"])
    def resume_schedules(self, request: request.Request, *args, **kwargs) -> response.Response:
        """
        Resume materialization for several models that were suspended after repeated failures.

        Accepts a list of view IDs in the request body: {"view_ids": ["id1", "id2", ...]}
        This endpoint is idempotent - calling it on models that are already running is safe.
        """
        from products.data_modeling.backend.facade.api import unsuspend_saved_query

        serializer = SavedQueryResumeSchedulesRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Skip rather than refuse, so one id the caller cannot edit does not cost them the rest of
        # the batch. Every skipped id looks the same from outside, whether it is absent, in another
        # project, deleted, or denied - the response would otherwise confirm that a model exists.
        candidates = list(
            DataWarehouseSavedQuery.objects.filter(
                id__in=serializer.validated_data["view_ids"], team_id=self.team_id
            ).exclude(deleted=True)
        )
        self.user_access_control.preload_object_access_controls(cast(list[Model], candidates))
        for saved_query in candidates:
            if self.user_access_control.check_access_level_for_object(saved_query, "editor"):
                unsuspend_saved_query(saved_query)
        return response.Response(status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        request=lineage.SavedQueryLineageRequestSerializer, responses={200: lineage.SavedQueryAncestorsSerializer}
    )
    @action(methods=["POST"], detail=True)
    def ancestors(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Return the ancestors of this saved query.

        By default, we return every ancestor. The `level` parameter bounds how many hops back
        to walk, so 1 gives the immediate parents.
        """
        saved_query = self.get_object()
        ancestors = lineage._related_saved_queries(saved_query, upstream=True, max_depth=lineage._parse_level(request))
        return response.Response({"ancestors": ancestors})

    @extend_schema(
        request=lineage.SavedQueryLineageRequestSerializer, responses={200: lineage.SavedQueryDescendantsSerializer}
    )
    @action(methods=["POST"], detail=True)
    def descendants(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Return the descendants of this saved query.

        By default, we return every descendant. The `level` parameter bounds how many hops
        forward to walk, so 1 gives the immediate children.
        """
        saved_query = self.get_object()
        descendants = lineage._related_saved_queries(
            saved_query, upstream=False, max_depth=lineage._parse_level(request)
        )
        return response.Response({"descendants": descendants})

    @action(methods=["GET"], detail=True, required_scopes=["activity_log:read"])
    def activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        item_id = kwargs["pk"]
        if not DataWarehouseSavedQuery.objects.filter(id=item_id, team_id=self.team_id).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        activity_page = load_activity(
            scope="DataWarehouseSavedQuery",
            team_id=self.team_id,
            item_ids=[str(item_id)],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["POST"], detail=True)
    def cancel(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Cancel a running saved query workflow."""
        saved_query = self.get_object()

        targets = {
            _CancelTarget(workflow_id=job.workflow_id, workflow_run_id=job.workflow_run_id)
            for job in DataModelingJob.objects.filter(
                team_id=self.team_id,
                saved_query=saved_query,
                status=DataModelingJob.Status.RUNNING,
            )
            if job.workflow_id
        }

        if not targets:
            return response.Response(
                {"error": "Cannot cancel a query that is not running"}, status=status.HTTP_400_BAD_REQUEST
            )

        temporal = sync_connect()
        failed = False

        for target in sorted(targets, key=lambda target: target.workflow_id):
            try:
                workflow_handle = temporal.get_workflow_handle(target.workflow_id, run_id=target.workflow_run_id)
                async_to_sync(workflow_handle.cancel)()
            except Exception as e:
                failed = True
                logger.exception(
                    "Failed to cancel workflow",
                    saved_query_id=str(saved_query.id),
                    workflow_id=target.workflow_id,
                    error=str(e),
                )

        if failed:
            return response.Response(
                {"error": "Failed to cancel workflow"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        saved_query.status = DataWarehouseSavedQuery.Status.CANCELLED
        saved_query.save()

        log_activity(
            organization_id=self.team.organization_id,
            team_id=self.team_id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
            item_id=saved_query.id,
            scope="DataWarehouseSavedQuery",
            activity="sync_cancelled",
            detail=Detail(name=saved_query.name),
        )

        return response.Response(status=status.HTTP_200_OK)

    @extend_schema(request=None, responses={200: lineage.SavedQueryDependenciesSerializer})
    @action(methods=["GET"], detail=True)
    def dependencies(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Return the count of immediate upstream and downstream dependencies for this saved query."""
        saved_query = self.get_object()
        return response.Response(
            {
                "upstream_count": len(lineage._related_saved_queries(saved_query, upstream=True, max_depth=1)),
                "downstream_count": len(lineage._related_saved_queries(saved_query, upstream=False, max_depth=1)),
            }
        )

    @action(methods=["GET"], detail=True, required_scopes=["warehouse_view:read"])
    def run_history(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Return the recent run history (up to 5 most recent) for this materialized view."""
        saved_query = self.get_object()

        # Get the 5 most recent runs
        jobs = (
            DataModelingJob.objects.filter(saved_query=saved_query)
            .order_by("-last_run_at")[:5]
            .values("status", "last_run_at")
        )

        run_history = [{"status": job["status"], "timestamp": job["last_run_at"]} for job in jobs]

        return response.Response({"run_history": run_history})
