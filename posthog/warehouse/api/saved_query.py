import uuid
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import OuterRef, Prefetch, Q, Subquery, TextField
from django.db.models.functions import Cast

import structlog
from asgiref.sync import async_to_sync
from loginas.utils import is_impersonated_session
from rest_framework import exceptions, filters, request, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from temporalio.client import ScheduleActionExecutionStartWorkflow

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database, SerializedField, serialize_fields
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import FindPlaceholders
from posthog.hogql.printer import prepare_and_print_ast

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import Team
from posthog.models.activity_logging.activity_log import (
    ActivityLog,
    Change,
    Detail,
    changes_between,
    load_activity,
    log_activity,
)
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.temporal.common.client import sync_connect
from posthog.warehouse.data_load.saved_query_service import (
    delete_saved_query_schedule,
    pause_saved_query_schedule,
    recreate_model_paths,
    saved_query_workflow_exists,
    sync_saved_query_workflow,
    trigger_saved_query_schedule,
    unpause_saved_query_schedule,
)
from posthog.warehouse.models import (
    CLICKHOUSE_HOGQL_MAPPING,
    DataModelingJob,
    DataWarehouseJoin,
    DataWarehouseModelPath,
    DataWarehouseSavedQuery,
    clean_type,
)
from posthog.warehouse.models.external_data_schema import (
    sync_frequency_interval_to_sync_frequency,
    sync_frequency_to_sync_frequency_interval,
)

logger = structlog.get_logger(__name__)


class DataWarehouseSavedQuerySerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    columns = serializers.SerializerMethodField(read_only=True)
    sync_frequency = serializers.SerializerMethodField()
    latest_history_id = serializers.SerializerMethodField(read_only=True)
    last_run_at = serializers.SerializerMethodField(read_only=True)
    edited_history_id = serializers.CharField(write_only=True, required=False, allow_null=True)
    soft_update = serializers.BooleanField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = DataWarehouseSavedQuery
        fields = [
            "id",
            "deleted",
            "name",
            "query",
            "created_by",
            "created_at",
            "sync_frequency",
            "columns",
            "status",
            "last_run_at",
            "latest_error",
            "edited_history_id",
            "latest_history_id",
            "soft_update",
            "is_materialized",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "columns",
            "status",
            "last_run_at",
            "latest_error",
            "latest_history_id",
            "is_materialized",
        ]
        extra_kwargs = {
            "soft_update": {"write_only": True},
        }

    def get_last_run_at(self, view: DataWarehouseSavedQuery) -> datetime | None:
        try:
            jobs = view.jobs  # type: ignore
            if len(jobs) > 0:
                return jobs[0].last_run_at
        except:
            pass

        return view.last_run_at

    def get_columns(self, view: DataWarehouseSavedQuery) -> list[SerializedField]:
        team_id = self.context["team_id"]
        database = self.context.get("database", None)
        if not database:
            database = Database.create_for(team_id=team_id)

        context = HogQLContext(team_id=team_id, database=database)

        fields = serialize_fields(view.hogql_definition().fields, context, view.name_chain, table_type="external")
        return [
            SerializedField(
                key=field.name,
                name=field.name,
                type=field.type,
                schema_valid=field.schema_valid,
                fields=field.fields,
                table=field.table,
                chain=field.chain,
            )
            for field in fields
        ]

    def get_sync_frequency(self, schema: DataWarehouseSavedQuery):
        return sync_frequency_interval_to_sync_frequency(schema.sync_frequency_interval)

    def get_latest_history_id(self, view: DataWarehouseSavedQuery):
        # First check if we have an activity log from a recent creation/update
        if (
            "activity_log" in self.context
            and self.context["activity_log"]
            and self.context["activity_log"].item_id == str(view.id)
        ):
            return self.context["activity_log"].id

        # Otherwise check for annotated field from queryset
        if hasattr(view, "latest_activity_id"):
            return view.latest_activity_id

        return None

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        soft_update = validated_data.pop("soft_update", False)
        view = DataWarehouseSavedQuery(**validated_data)

        if not soft_update:
            try:
                # The columns will be inferred from the query
                client_types = self.context["request"].data.get("types", [])
                if len(client_types) == 0:
                    view.columns = view.get_columns()
                else:
                    columns = {
                        str(item[0]): {
                            "hogql": CLICKHOUSE_HOGQL_MAPPING[clean_type(str(item[1]))].__name__,
                            "clickhouse": item[1],
                            "valid": True,
                        }
                        for item in client_types
                    }
                    view.columns = columns

                view.external_tables = view.s3_tables
            except Exception:
                raise serializers.ValidationError("Failed to retrieve types for view")

        with transaction.atomic():
            view.save()
            try:
                DataWarehouseModelPath.objects.create_from_saved_query(view)
            except Exception:
                # For now, do not fail saved query creation if we cannot model-ize it.
                # Later, after bugs and errors have been ironed out, we may tie these two
                # closer together.
                logger.exception("Failed to create model path when creating view %s", view.name)

            team = Team.objects.get(id=view.team_id)

            activity_log = log_activity(
                organization_id=team.organization_id,
                team_id=team.id,
                user=view.created_by,
                was_impersonated=is_impersonated_session(self.context["request"]),
                item_id=view.id,
                scope="DataWarehouseSavedQuery",
                activity="created",
                detail=Detail(
                    name=view.name,
                    changes=[
                        Change(
                            field="query",
                            action="created",
                            type="DataWarehouseSavedQuery",
                            before=None,
                            after=view.query,
                        )
                    ],
                ),
            )

            # Store the activity log in the serializer context
            if activity_log:
                self.context["activity_log"] = activity_log

        return view

    def update(self, instance: Any, validated_data: Any) -> Any:
        try:
            before_update = DataWarehouseSavedQuery.objects.get(pk=instance.id)
        except DataWarehouseSavedQuery.DoesNotExist:
            before_update = None

        sync_frequency = self.context["request"].data.get("sync_frequency", None)
        was_sync_frequency_updated = False

        soft_update = validated_data.pop("soft_update", False)

        with transaction.atomic():
            locked_instance = DataWarehouseSavedQuery.objects.select_for_update().get(pk=instance.pk)

            # Get latest activity log for this model

            if validated_data.get("query", None) and not soft_update:
                edited_history_id = self.context["request"].data.get("edited_history_id", None)
                latest_activity_id = (
                    ActivityLog.objects.filter(item_id=locked_instance.id, scope="DataWarehouseSavedQuery")
                    .order_by("-created_at")
                    .values_list("id", flat=True)
                    .first()
                )

                if str(edited_history_id) != str(latest_activity_id):
                    raise serializers.ValidationError("The query was modified by someone else.")

            if sync_frequency == "never":
                pause_saved_query_schedule(str(locked_instance.id))
                locked_instance.sync_frequency_interval = None
                validated_data["sync_frequency_interval"] = None
                validated_data["is_materialized"] = True
            elif sync_frequency:
                sync_frequency_interval = sync_frequency_to_sync_frequency_interval(sync_frequency)
                validated_data["sync_frequency_interval"] = sync_frequency_interval
                was_sync_frequency_updated = True
                locked_instance.sync_frequency_interval = sync_frequency_interval
                validated_data["is_materialized"] = True

            view: DataWarehouseSavedQuery = super().update(locked_instance, validated_data)

            # Only update columns and status if the query has changed
            if "query" in validated_data:
                try:
                    # The columns will be inferred from the query
                    client_types = self.context["request"].data.get("types", [])
                    if len(client_types) == 0:
                        view.columns = view.get_columns()
                    else:
                        columns = {
                            str(item[0]): {
                                "hogql": CLICKHOUSE_HOGQL_MAPPING[clean_type(str(item[1]))].__name__,
                                "clickhouse": item[1],
                                "valid": True,
                            }
                            for item in client_types
                        }
                        view.columns = columns

                    view.external_tables = view.s3_tables
                except RecursionError:
                    raise serializers.ValidationError("Model contains a cycle")
                except Exception:
                    raise serializers.ValidationError("Failed to retrieve types for view")

                view.status = DataWarehouseSavedQuery.Status.MODIFIED
                view.save()

            try:
                DataWarehouseModelPath.objects.update_from_saved_query(view)
            except Exception:
                logger.exception("Failed to update model path when updating view %s", view.name)

            team = Team.objects.get(id=view.team_id)

            changes = changes_between("DataWarehouseSavedQuery", previous=before_update, current=view)
            activity_log = log_activity(
                organization_id=team.organization_id,
                team_id=team.id,
                user=self.context["request"].user,
                was_impersonated=is_impersonated_session(self.context["request"]),
                item_id=view.id,
                scope="DataWarehouseSavedQuery",
                activity="updated",
                detail=Detail(name=view.name, changes=changes),
            )

            # Store the activity log in the serializer context
            if activity_log:
                self.context["activity_log"] = activity_log
            else:
                # get latest activity log for this model
                latest_activity_log = (
                    ActivityLog.objects.filter(item_id=locked_instance.id, scope="DataWarehouseSavedQuery")
                    .order_by("-created_at")
                    .first()
                )
                self.context["activity_log"] = latest_activity_log

            if sync_frequency and sync_frequency != "never":
                recreate_model_paths(view)

        if was_sync_frequency_updated:
            schedule_exists = saved_query_workflow_exists(str(instance.id))
            if schedule_exists and before_update and before_update.sync_frequency_interval is None:
                unpause_saved_query_schedule(str(instance.id))
            sync_saved_query_workflow(view, create=not schedule_exists)

        return view

    def validate_query(self, query):
        team_id = self.context["team_id"]

        context = HogQLContext(team_id=team_id, enable_select_queries=True)
        select_ast = parse_select(query["query"])

        find_placeholders = FindPlaceholders()
        find_placeholders.visit(select_ast)
        if len(find_placeholders.placeholder_fields) > 0:
            placeholder = find_placeholders.placeholder_fields.pop()
            placeholder_string = ".".join(str(field) for field in placeholder if field is not None)
            raise exceptions.ValidationError(
                detail=f"Variables like {'{'}{placeholder_string}{'}'} are not allowed in views"
            )
        elif find_placeholders.placeholder_expressions or find_placeholders.has_filters:
            raise exceptions.ValidationError(detail="Filters and placeholder expressions are not allowed in views")

        try:
            prepare_and_print_ast(
                node=select_ast,
                context=context,
                dialect="clickhouse",
                stack=None,
                settings=None,
            )
        except Exception as err:
            if isinstance(err, ExposedHogQLError):
                error = str(err)
                raise exceptions.ValidationError(detail=f"Invalid query: {error}")
            elif not settings.DEBUG:
                # We don't want to accidentally expose too much data via errors
                raise exceptions.ValidationError(detail=f"Unexpected {err.__class__.__name__}")

        return query

    def validate_name(self, name):
        # if it's an upsert, we don't want to validate the name
        if self.instance is not None and isinstance(self.instance, DataWarehouseSavedQuery):
            if self.instance.name == name:
                return name

        name_exists_in_hogql_database = self.context["database"].has_table(name)
        if name_exists_in_hogql_database:
            raise serializers.ValidationError("A table with this name already exists.")

        return name


class DataWarehouseSavedQueryPagination(PageNumberPagination):
    page_size = 1000


class DataWarehouseSavedQueryViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete Warehouse Tables.
    """

    scope_object = "warehouse_view"
    queryset = DataWarehouseSavedQuery.objects.all()
    serializer_class = DataWarehouseSavedQuerySerializer
    pagination_class = DataWarehouseSavedQueryPagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    ordering = "-created_at"

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["database"] = Database.create_for(team_id=self.team_id)
        return context

    def safely_get_queryset(self, queryset):
        base_queryset = (
            queryset.prefetch_related(
                "created_by",
                Prefetch(
                    "datamodelingjob_set", queryset=DataModelingJob.objects.order_by("-last_run_at")[:1], to_attr="jobs"
                ),
            )
            .filter(managed_viewset__isnull=True)  # Ignore managed views for now
            .exclude(deleted=True)
            .order_by(self.ordering)
        )

        # Only annotate with latest activity ID for list operations, not for single object retrieves
        # This avoids the annotation when we're getting a single object for update/create/etc.
        action = self.action if hasattr(self, "action") else None
        if action == "list" or action == "retrieve":
            # Add latest activity id annotation to avoid N+1 queries
            latest_activity = (
                ActivityLog.objects.filter(
                    scope="DataWarehouseSavedQuery",
                    item_id=Cast(OuterRef("id"), output_field=TextField()),
                    team_id=self.team_id,
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
            # Update logic
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
        instance: DataWarehouseSavedQuery = self.get_object()

        delete_saved_query_schedule(str(instance.id))

        for join in DataWarehouseJoin.objects.filter(
            Q(team_id=instance.team_id) & (Q(source_table_name=instance.name) | Q(joining_table_name=instance.name))
        ).exclude(deleted=True):
            join.soft_delete()

        if instance.table is not None:
            instance.table.soft_delete()

        instance.soft_delete()

        return response.Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["POST"], detail=True)
    def run(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Run this saved query."""
        saved_query = self.get_object()

        trigger_saved_query_schedule(saved_query)

        return response.Response(status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=True)
    def revert_materialization(self, request: request.Request, *args, **kwargs) -> response.Response:
        """
        Undo materialization, revert back to the original view.
        (i.e. delete the materialized table and the schedule)
        """
        saved_query: DataWarehouseSavedQuery = self.get_object()
        saved_query.revert_materialization()

        return response.Response(status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=True)
    def ancestors(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Return the ancestors of this saved query.

        By default, we return the immediate parents. The `level` parameter can be used to
        look further back into the ancestor tree. If `level` overshoots (i.e. points to only
        ancestors beyond the root), we return an empty list.
        """
        up_to_level = request.data.get("level", None)

        saved_query = self.get_object()
        saved_query_id = saved_query.id.hex
        lquery = f"*{{1,}}.{saved_query_id}"

        paths = DataWarehouseModelPath.objects.filter(team=saved_query.team, path__lquery=lquery)

        if not paths:
            return response.Response({"ancestors": []})

        ancestors: set[str | uuid.UUID] = set()
        for model_path in paths:
            if up_to_level is None:
                start = 0
            else:
                start = (int(up_to_level) * -1) - 1

            ancestors = ancestors.union(map(try_convert_to_uuid, model_path.path[start:-1]))

        return response.Response({"ancestors": ancestors})

    @action(methods=["POST"], detail=True)
    def descendants(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Return the descendants of this saved query.

        By default, we return the immediate children. The `level` parameter can be used to
        look further ahead into the descendants tree. If `level` overshoots (i.e. points to only
        descendants further than a leaf), we return an empty list.
        """
        up_to_level = request.data.get("level", None)

        saved_query = self.get_object()
        saved_query_id = saved_query.id.hex

        lquery = f"*.{saved_query_id}.*{{1,}}"
        paths = DataWarehouseModelPath.objects.filter(team=saved_query.team, path__lquery=lquery)

        if not paths:
            return response.Response({"descendants": []})

        descendants: set[str | uuid.UUID] = set()
        for model_path in paths:
            start = model_path.path.index(saved_query_id) + 1
            if up_to_level is None:
                end = len(model_path.path)
            else:
                end = start + up_to_level

            descendants = descendants.union(map(try_convert_to_uuid, model_path.path[start:end]))

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

        if saved_query.status != DataWarehouseSavedQuery.Status.RUNNING:
            return response.Response(
                {"error": "Cannot cancel a query that is not running"}, status=status.HTTP_400_BAD_REQUEST
            )

        temporal = sync_connect()
        workflow_id = f"data-modeling-run-{saved_query.id.hex}"

        try:
            # Ad-hoc handling
            try:
                workflow_handle = temporal.get_workflow_handle(workflow_id)
                if workflow_handle:
                    async_to_sync(workflow_handle.cancel)()
            except Exception:
                logger.info("No ad-hoc workflow to cancel", workflow_id=workflow_id)

            # Schedule handling
            try:
                scheduled_workflow_handle = temporal.get_schedule_handle(str(saved_query.id))
                desc = async_to_sync(scheduled_workflow_handle.describe)()
                recent_actions = desc.info.running_actions
                if len(recent_actions) > 0:
                    most_recent_action = recent_actions[-1]
                    if isinstance(most_recent_action, ScheduleActionExecutionStartWorkflow):
                        workflow_id_to_cancel = most_recent_action.workflow_id
                    else:
                        logger.warning(
                            "Unexpected action type in schedule",
                            action_type=type(most_recent_action).__name__,
                        )

                    workflow_handle_to_cancel = temporal.get_workflow_handle(workflow_id_to_cancel)
                    if workflow_handle_to_cancel:
                        async_to_sync(workflow_handle_to_cancel.cancel)()
            except Exception:
                logger.info("No scheduled workflow to cancel", saved_query_id=str(saved_query.id))

            # Update saved query status, but not the data modeling job which occurs in the workflow
            # This is because the saved_query is used by our UI to prevent multiple cancellations
            saved_query.status = DataWarehouseSavedQuery.Status.CANCELLED
            saved_query.save()

            return response.Response(status=status.HTTP_200_OK)
        except Exception as e:
            logger.exception("Failed to cancel workflow", workflow_id=workflow_id, error=str(e))
            return response.Response(
                {"error": f"Failed to cancel workflow"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


def try_convert_to_uuid(s: str) -> uuid.UUID | str:
    try:
        return str(uuid.UUID(s))
    except ValueError:
        return s
