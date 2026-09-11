"""Saved-query request and response serializers."""

from datetime import datetime
from typing import Any, cast

from django.conf import settings
from django.db import transaction

import structlog
from drf_spectacular.utils import extend_schema_field
from rest_framework import exceptions, serializers
from rest_framework.pagination import PageNumberPagination

from posthog.schema import DataWarehouseManagedViewsetKind

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database, SerializedField, serialize_fields
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import FindPlaceholders
from posthog.hogql.printer import prepare_and_print_ast

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer
from posthog.errors import ExposedCHQueryError
from posthog.exceptions_capture import capture_exception
from posthog.helpers.impersonation import is_impersonated
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import ActivityLog, Change, Detail, changes_between, log_activity
from posthog.rate_limit import PersonalApiKeyOrUserRateThrottle
from posthog.rbac.query_access import assert_user_can_read_query

from products.access_control.backend.presentation.access_control import UserAccessControlSerializerMixin
from products.data_modeling.backend.facade.api import MAX_LOOKBACK_SECONDS, get_incremental_config
from products.data_modeling.backend.facade.models import (
    DataModelingJob,
    DataModelingJobEngine,
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryColumnAnnotation,
)
from products.data_tools.backend.facade.models import DataWarehouseSavedQueryFolder
from products.data_warehouse.backend.presentation.views.column_annotation_base import (
    DESCRIPTION_HELP_TEXT,
    upsert_annotation,
)
from products.warehouse_sources.backend.facade.hogql import (
    get_view_or_table_by_name,
    hogql_type_name_for_clickhouse_type,
)
from products.warehouse_sources.backend.facade.models import sync_frequency_to_sync_frequency_interval

from . import frequency

logger = structlog.get_logger(__name__)


def _view_types_validation_error(e: Exception) -> serializers.ValidationError:
    # Column inference runs the HogQL-to-ClickHouse path, so a raw exception can carry stack
    # traces, internal table or column names, and S3 URIs. Surface only the errors already marked
    # user-safe; reduce everything else to its class name. Mirrors validate_query below, which
    # keeps the full cause in error tracking and logs instead of the response.
    if isinstance(e, ExposedHogQLError | ExposedCHQueryError):
        return serializers.ValidationError(f"Failed to retrieve types for view: {e}")
    return serializers.ValidationError(f"Failed to retrieve types for view: unexpected {type(e).__name__}")


# A DataWarehouseSavedQuery's activity log also records materialization syncs and status
# transitions (activity="sync_triggered", status changes) that advance the log without the query
# being edited. Optimistic-concurrency ("modified by someone else") must key off the latest activity
# that actually changed the query — otherwise every background sync of a materialized view looks
# like a foreign edit and blocks the next save. This filter scopes activity lookups to query edits.
QUERY_CHANGE_ACTIVITY_FILTER = {"detail__changes__contains": [{"field": "query"}]}

VIEW_DESCRIPTION_HELP_TEXT = (
    "Semantic description of what this view represents, surfaced to AI agents. Set it to describe the "
    "view; send an empty string to clear it. Per-column descriptions are read back in `columns` and set "
    "via the saved-query column annotation endpoints. " + DESCRIPTION_HELP_TEXT
)


def view_annotation_map(view: DataWarehouseSavedQuery) -> dict[str, str]:
    """`{column_name: description}` from a view's column annotations (``""`` = view-level)."""
    return {a.column_name: a.description for a in view.column_annotations.all()}


class ViewDescriptionField(serializers.CharField):
    """View-level description, stored as a column annotation with an empty `column_name`.

    Reads the annotation for display; on write the serializer's create/update upserts or clears it. The
    view model has no `description` column, so the value is resolved here rather than bound to the model.
    """

    def get_attribute(self, instance: DataWarehouseSavedQuery) -> str | None:
        return view_annotation_map(instance).get("")


class DataWarehouseSavedQuerySerializerMixin:
    """Shared methods for DataWarehouseSavedQuery serializers.

    This mixin is intended to be used with serializers.ModelSerializer subclasses.
    """

    def _serving_run(self, view: DataWarehouseSavedQuery) -> DataModelingJob | None:
        """The newest materialization run that serves this view, or None if it has never run.

        Prefers the prefetched job so a list of views costs one query. Falls back to a lookup for
        the detail route, which has no prefetch.
        """
        try:
            jobs = view.jobs  # type: ignore[attr-defined]
            return jobs[0] if jobs else None
        except AttributeError:
            return (
                DataModelingJob.objects.filter(saved_query_id=view.id)
                .exclude(engine=DataModelingJobEngine.DUCKGRES)
                .order_by("-last_run_at")
                .first()
            )

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_last_run_at(self, view: DataWarehouseSavedQuery) -> datetime | None:
        run = self._serving_run(view)
        return run.last_run_at if run is not None else view.last_run_at

    @extend_schema_field(serializers.ChoiceField(choices=DataWarehouseSavedQuery.Status.choices, allow_null=True))
    def get_status(self, view: DataWarehouseSavedQuery) -> str | None:
        run = self._serving_run(view)
        if run is None:
            return view.status
        # Modified means "edited and not materialized since", which no run can express. A run that
        # happened after the edit answers it, so the column only wins while the edit is the newer fact.
        edited_since_the_run = (
            view.status == DataWarehouseSavedQuery.Status.MODIFIED
            and view.updated_at is not None
            and view.updated_at > run.last_run_at
        )
        return view.status if edited_since_the_run else run.status

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_latest_error(self, view: DataWarehouseSavedQuery) -> str | None:
        run = self._serving_run(view)
        return run.error if run is not None else view.latest_error

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_sync_frequency(self, schema: DataWarehouseSavedQuery):
        return frequency.resolve_sync_frequency(self.root, schema)  # type: ignore[attr-defined]

    @extend_schema_field(serializers.BooleanField())
    def get_is_incremental(self, view: DataWarehouseSavedQuery) -> bool:
        return get_incremental_config(view) is not None

    @extend_schema_field(frequency.SyncFrequencyBoundsSerializer())
    def get_sync_frequency_bounds(self, view: DataWarehouseSavedQuery) -> dict[str, Any]:
        from products.data_modeling.backend.facade.api import saved_query_target_bounds

        if view.managed_viewset is not None:
            return frequency._unbounded_frequency_payload("managed_viewset")

        resolved = saved_query_target_bounds(view.team_id, view.pk)
        if resolved is None:
            return frequency._unbounded_frequency_payload("no_node")
        visible = frequency.visible_blocker_names(resolved, self.user_access_control, team_id=view.team_id)  # type: ignore[attr-defined]
        return frequency._frequency_bounds_payload(resolved, visible)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_managed_viewset_kind(self, view: DataWarehouseSavedQuery) -> DataWarehouseManagedViewsetKind | None:
        return cast(DataWarehouseManagedViewsetKind, view.managed_viewset.kind) if view.managed_viewset else None

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_columns(self, view: DataWarehouseSavedQuery) -> list[SerializedField]:
        query = view.query or {}
        if not isinstance(query, dict) or "query" not in query:
            return []

        team_id = self.context["team_id"]  # type: ignore[attr-defined]
        database = self.context.get("database", None)  # type: ignore[attr-defined]
        if not database:
            database = Database.create_for(
                team_id=team_id,
                user=cast(User, self.context["request"].user),  # type: ignore[attr-defined]
            )

        context = HogQLContext(team_id=team_id, database=database)

        descriptions = view_annotation_map(view)
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
                description=descriptions.get(field.name),
            )
            for field in fields
        ]


class DataWarehouseSavedQueryMinimalSerializer(
    DataWarehouseSavedQuerySerializerMixin, UserAccessControlSerializerMixin, serializers.ModelSerializer
):
    """Lightweight serializer for list views - excludes large query field to reduce memory usage."""

    created_by = UserBasicSerializer(read_only=True)
    columns = serializers.SerializerMethodField(read_only=True)
    description = ViewDescriptionField(read_only=True, help_text=VIEW_DESCRIPTION_HELP_TEXT)
    sync_frequency = serializers.SerializerMethodField()
    last_run_at = serializers.SerializerMethodField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)
    latest_error = serializers.SerializerMethodField(read_only=True)
    managed_viewset_kind = serializers.SerializerMethodField(read_only=True)
    folder_id = serializers.UUIDField(source="folder.id", read_only=True, allow_null=True)
    folder_name = serializers.CharField(source="folder.name", read_only=True, allow_null=True)
    is_incremental = serializers.SerializerMethodField(
        read_only=True,
        help_text="Whether this view is set up to update incrementally. A run can still rebuild the "
        "whole table, for example on the first run or after the query changes.",
    )

    class Meta:
        model = DataWarehouseSavedQuery
        fields = [
            "id",
            "deleted",
            "name",
            "created_by",
            "created_at",
            "description",
            "sync_frequency",
            "columns",
            "status",
            "last_run_at",
            "managed_viewset_kind",
            "folder_id",
            "folder_name",
            "latest_error",
            "is_materialized",
            "is_incremental",
            "origin",
            "is_test",
            "expires_at",
            "user_access_level",
        ]
        read_only_fields = fields


def _clickhouse_types(columns: Any) -> dict[str, str] | None:
    """Pull the ClickHouse type out of each entry in a saved query's stored `columns` blob.

    Only used to spot a nullable unique key, which would silently duplicate rows on every run.
    """
    if not isinstance(columns, dict):
        return None
    types: dict[str, str] = {}
    for name, meta in columns.items():
        if isinstance(meta, dict) and isinstance(meta.get("clickhouse"), str):
            types[name] = meta["clickhouse"]
    return types or None


class SavedQuerySuspensionSerializer(serializers.Serializer):
    at = serializers.DateTimeField(help_text="When materialization was suspended.")
    reason = serializers.CharField(help_text="Error from the materialization run that tripped suspension.")
    job_id = serializers.CharField(help_text="Materialization job that tripped suspension.")


class IncrementalConfigSerializer(serializers.Serializer):
    """How a view updates its materialized table in place rather than rebuilding it."""

    enabled = serializers.BooleanField(
        default=False, help_text="Whether runs update the table incrementally instead of rebuilding it."
    )
    incremental_key = serializers.CharField(
        help_text="Output column whose advancing value marks rows as new. Each run reads only rows at "
        "or after the last run's highest value for it. When the query groups, this must be one of the "
        "grouped columns, so every group a run touches is recomputed in full.",
    )
    unique_key = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=False,
        help_text="Output columns that identify a row, used to match recomputed rows against stored "
        "ones. Must include every GROUP BY column. These columns can never be null.",
    )
    lookback_seconds = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        max_value=MAX_LOOKBACK_SECONDS,
        help_text="How far back before the last run's high point to re-read, so late-arriving data is "
        "picked up. Only applies when the incremental key is a date or time.",
    )


class IncrementalStateSerializer(serializers.Serializer):
    """Read-only progress written by the materialization run."""

    watermark = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Highest incremental key value written so far. The next run starts here.",
    )
    definition_fingerprint = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Fingerprint of the query, incremental key, and unique key the stored rows were "
        "built from. When it stops matching, the next run rebuilds the whole table. Lookback is "
        "not part of it: changing lookback never forces a rebuild.",
    )
    last_full_refresh_at = serializers.CharField(
        allow_null=True, required=False, help_text="When the table was last rebuilt from scratch."
    )
    last_run_mode = serializers.ChoiceField(
        choices=[("incremental", "incremental"), ("full_refresh", "full_refresh")],
        allow_null=True,
        required=False,
        help_text="Whether the last run updated the table or rebuilt it.",
    )


class DataWarehouseSavedQuerySerializer(
    DataWarehouseSavedQuerySerializerMixin, UserAccessControlSerializerMixin, serializers.ModelSerializer
):
    @extend_schema_field(
        {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["HogQLQuery"], "default": "HogQLQuery"},
                "query": {"type": "string"},
            },
            "required": ["query"],
        }
    )
    class QueryDefinitionField(serializers.JSONField):
        pass

    created_by = UserBasicSerializer(read_only=True)
    columns = serializers.SerializerMethodField(read_only=True)
    query = QueryDefinitionField(
        help_text='HogQL query definition as a JSON object with a "query" key containing the SQL string and a "kind" key (always "HogQLQuery"). Format the SQL string multi-line with indentation and inline `--` comments for non-obvious logic — the SQL editor renders it verbatim, so avoid minified single-line SQL. Example: {"kind": "HogQLQuery", "query": "SELECT\\n    event,\\n    count() AS cnt\\nFROM events\\nGROUP BY event\\nLIMIT 100"}',
    )
    sync_frequency = frequency.SyncFrequencyField(
        help_text=(
            "How often to materialize this view. One of '15min', '30min', '1hour', '6hour', '12hour', "
            "'24hour', '7day', '30day', or 'never' to pause scheduled materialization. 15min is the fastest "
            "cadence available. Null means no scheduled materialization. Read back after a write, this "
            "reflects the cadence stored on the view's DAG node."
        ),
    )
    sync_frequency_bounds = serializers.SerializerMethodField(
        read_only=True, help_text=frequency.SYNC_FREQUENCY_BOUNDS_HELP_TEXT
    )
    latest_history_id = serializers.SerializerMethodField(read_only=True)
    last_run_at = serializers.SerializerMethodField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)
    latest_error = serializers.SerializerMethodField(read_only=True)
    managed_viewset_kind = serializers.SerializerMethodField(read_only=True)
    suspended = serializers.SerializerMethodField(read_only=True)
    folder_id = TeamScopedPrimaryKeyRelatedField(
        source="folder",
        queryset=DataWarehouseSavedQueryFolder.objects.all(),
        required=False,
        allow_null=True,
        help_text="Optional folder ID used to organize this view in the SQL editor sidebar.",
    )
    folder_name = serializers.CharField(
        source="folder.name",
        read_only=True,
        allow_null=True,
        help_text="Folder name used to organize this view in the SQL editor sidebar.",
    )
    edited_history_id = serializers.CharField(
        write_only=True,
        required=False,
        allow_null=True,
        help_text="Activity log ID from the last known edit. Used for conflict detection.",
    )
    soft_update = serializers.BooleanField(
        write_only=True,
        required=False,
        allow_null=True,
        help_text="If true, skip column inference and validation. For saving drafts.",
    )
    dag_id = serializers.UUIDField(
        write_only=True, required=False, allow_null=True, help_text="Optional DAG to place this view into"
    )
    description = ViewDescriptionField(
        required=False, allow_blank=True, allow_null=True, help_text=VIEW_DESCRIPTION_HELP_TEXT
    )
    incremental = IncrementalConfigSerializer(
        source="incremental_config",
        required=False,
        allow_null=True,
        help_text="Update the materialized table in place instead of rebuilding it. Null or absent "
        "means every run rebuilds the whole table.",
    )
    incremental_state = IncrementalStateSerializer(
        read_only=True,
        allow_null=True,
        help_text="How far incremental materialization has progressed. Null until the first run "
        "records any. Written by the materialization run, not by this API.",
    )

    class Meta:
        model = DataWarehouseSavedQuery
        fields = [
            "id",
            "deleted",
            "name",
            "query",
            "incremental",
            "incremental_state",
            "created_by",
            "created_at",
            "description",
            "sync_frequency",
            "sync_frequency_bounds",
            "columns",
            "status",
            "last_run_at",
            "managed_viewset_kind",
            "folder_id",
            "folder_name",
            "latest_error",
            "edited_history_id",
            "latest_history_id",
            "soft_update",
            "dag_id",
            "is_materialized",
            "origin",
            "is_test",
            "expires_at",
            "user_access_level",
            "suspended",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "columns",
            "incremental_state",
            "status",
            "last_run_at",
            "managed_viewset_kind",
            "sync_frequency_bounds",
            "folder_name",
            "latest_error",
            "latest_history_id",
            "user_access_level",
            "is_materialized",
            "origin",
            "expires_at",
            "suspended",
        ]
        extra_kwargs = {
            "soft_update": {"write_only": True},
            "name": {
                "help_text": "Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.",
            },
        }

    def _write_view_description(self, view: DataWarehouseSavedQuery, description: str | None) -> None:
        team_id = self.context["team_id"]
        if description:
            upsert_annotation(
                DataWarehouseSavedQueryColumnAnnotation,
                team_id,
                parent_field="saved_query",
                parent=view,
                column_name="",
                description=description,
            )
        else:
            DataWarehouseSavedQueryColumnAnnotation.objects.for_team(team_id).filter(
                saved_query=view, column_name=""
            ).delete()

    @extend_schema_field(serializers.IntegerField(allow_null=True))
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

    @extend_schema_field(
        serializers.DictField(
            child=SavedQuerySuspensionSerializer(),
            help_text="Engines this query's materialization is suspended for after repeated failures. "
            "Suspended engines are skipped by scheduled runs until the query is resumed.",
        )
    )
    def get_suspended(self, view: DataWarehouseSavedQuery) -> dict[str, Any]:
        from products.data_modeling.backend.facade.api import suspension_state_for_saved_query

        return {
            engine: SavedQuerySuspensionSerializer(entry).data
            for engine, entry in suspension_state_for_saved_query(view).items()
        }

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        validated_data["origin"] = DataWarehouseSavedQuery.Origin.DATA_WAREHOUSE
        soft_update = validated_data.pop("soft_update", False)
        dag_id = validated_data.pop("dag_id", None)
        has_description = "description" in validated_data
        description = validated_data.pop("description", None)
        # Sync cadence is configured via materialization, not on creation — drop it so it
        # isn't passed to the model constructor.
        validated_data.pop("sync_frequency", None)
        view = DataWarehouseSavedQuery(**validated_data)

        if not soft_update:
            try:
                # The columns will be inferred from the query
                client_types = self.context["request"].data.get("types", [])
                if len(client_types) == 0:
                    view.set_columns(view.get_columns(user=self.context["request"].user))
                else:
                    columns = {
                        str(item[0]): {
                            "hogql": hogql_type_name_for_clickhouse_type(str(item[1])),
                            "clickhouse": item[1],
                            "valid": True,
                        }
                        for item in client_types
                    }
                    view.set_columns(columns)

                view.external_tables = view.get_s3_tables(database=self.context["database"])
            except Exception as e:
                capture_exception(e)
                logger.exception("Failed to retrieve types for view %s", view.name)
                raise _view_types_validation_error(e)

        with transaction.atomic():
            view.save()
            if has_description:
                self._write_view_description(view, description)
            try:
                view.setup_model_paths()
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
                was_impersonated=is_impersonated(self.context["request"]),
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
        # best effort sync to new data modeling DAG representation
        try:
            from products.data_modeling.backend.facade.api import sync_saved_query_to_dag
            from products.data_modeling.backend.facade.models import DAG

            dag_obj = None
            if dag_id:
                try:
                    dag_obj = DAG.objects.get(id=dag_id, team_id=view.team_id)
                except DAG.DoesNotExist:
                    raise serializers.ValidationError({"dag_id": "Invalid DAG ID or DAG does not belong to this team"})
            sync_saved_query_to_dag(view, dag=dag_obj)
        except Exception as e:
            capture_exception(e)
            logger.exception("Failed to sync saved query to DAG", saved_query_name=view.name)
        return view

    def update(self, instance: Any, validated_data: Any) -> Any:
        dag_id = validated_data.pop("dag_id", None)
        has_description = "description" in validated_data
        description = validated_data.pop("description", None)

        if instance.managed_viewset is not None:
            raise serializers.ValidationError("Cannot update a query from a managed viewset")

        try:
            before_update = DataWarehouseSavedQuery.objects.get(pk=instance.id)
        except DataWarehouseSavedQuery.DoesNotExist:
            before_update = None

        sync_frequency = validated_data.pop("sync_frequency", None)

        if sync_frequency and sync_frequency != "never":
            # Scheduling a view is the same grant as materializing it directly.
            assert_user_can_read_query(
                instance.query,
                self.context["team_id"],
                cast(User, self.context["request"].user),
                database=self.context.get("database"),
            )

        # The frequency writes through to the DAG node's freshness target.
        frequency_changed = bool(sync_frequency)

        soft_update = validated_data.pop("soft_update", False)

        with transaction.atomic():
            locked_instance = DataWarehouseSavedQuery.objects.select_for_update().get(pk=instance.pk)

            # Get latest activity log for this model

            if validated_data.get("query", None) and not soft_update:
                edited_history_id = self.context["request"].data.get("edited_history_id", None)
                latest_activity_id = (
                    ActivityLog.objects.filter(
                        team_id=locked_instance.team_id,
                        item_id=locked_instance.id,
                        scope="DataWarehouseSavedQuery",
                        **QUERY_CHANGE_ACTIVITY_FILTER,
                    )
                    .order_by("-created_at")
                    .values_list("id", flat=True)
                    .first()
                )

                if str(edited_history_id) != str(latest_activity_id):
                    raise serializers.ValidationError("The query was modified by someone else.")

            if frequency_changed:
                # The node target is the only store of frequency intent. The interval column
                # stays NULL so a stale v1 schedule can never be revived from it.
                locked_instance.sync_frequency_interval = None
                validated_data["sync_frequency_interval"] = None

            view: DataWarehouseSavedQuery = super().update(locked_instance, validated_data)

            if frequency_changed:
                from products.data_modeling.backend.facade.api import (
                    UnsatisfiableFrequencyError,
                    UnsupportedFrequencyTargetError,
                    apply_saved_query_frequency_target,
                    declared_targets_by_saved_query,
                    saved_query_target_bounds,
                )

                target = (
                    None if sync_frequency == "never" else sync_frequency_to_sync_frequency_interval(sync_frequency)
                )
                previous_target = declared_targets_by_saved_query(view.team_id, [view.pk]).get(str(view.pk))
                # A refusal names what blocks the cadence, so it obeys the same grants the read
                # payload does — otherwise one rejected PATCH reads back a name the caller was
                # never shown. Withheld nodes fall back to generic prose inside the refusal.
                bounds = saved_query_target_bounds(view.team_id, view.pk)
                visible = (
                    frequency.visible_blocker_names(bounds, self.user_access_control, team_id=view.team_id)
                    if bounds is not None
                    else {}
                )
                try:
                    # Validates inside the transaction (a rejected frequency rolls the whole
                    # update back) and queues the schedule reconcile for after commit.
                    nodes_written = apply_saved_query_frequency_target(view, target, visible_names=visible)
                except (UnsatisfiableFrequencyError, UnsupportedFrequencyTargetError) as e:
                    raise serializers.ValidationError(str(e))
                if target is not None and nodes_written == 0:
                    raise serializers.ValidationError(
                        "Cannot set a materialization frequency: this view is not wired into the data "
                        "modeling DAG yet. Re-save the view to create its node, then set the frequency."
                    )

            if has_description:
                self._write_view_description(view, description)

            # Only update columns and status if the query has changed
            if "query" in validated_data:
                try:
                    # The columns will be inferred from the query
                    client_types = self.context["request"].data.get("types", [])
                    if len(client_types) == 0:
                        view.set_columns(view.get_columns(user=self.context["request"].user))
                    else:
                        columns = {
                            str(item[0]): {
                                "hogql": hogql_type_name_for_clickhouse_type(str(item[1])),
                                "clickhouse": item[1],
                                "valid": True,
                            }
                            for item in client_types
                        }
                        view.set_columns(columns)

                    view.external_tables = view.get_s3_tables(database=self.context["database"])
                except RecursionError:
                    raise serializers.ValidationError("Model contains a cycle")
                except Exception as e:
                    capture_exception(e)
                    logger.exception("Failed to retrieve types for view %s", view.name)
                    raise _view_types_validation_error(e)

                view.status = DataWarehouseSavedQuery.Status.MODIFIED
                view.save()

            try:
                view.setup_model_paths()
            except Exception as e:
                capture_exception(e)
                logger.exception("Failed to update model path when updating view %s", view.name)

            team = Team.objects.get(id=view.team_id)

            changes = changes_between("DataWarehouseSavedQuery", previous=before_update, current=view)
            changes = [
                Change(
                    type=change.type,
                    action=change.action,
                    field=change.field,
                    before=getattr(change.before, "name", change.before) if change.field == "folder" else change.before,
                    after=getattr(change.after, "name", change.after) if change.field == "folder" else change.after,
                )
                for change in changes
            ]
            if frequency_changed and previous_target != target:
                # The cadence lives on the DAG node, so changes_between() sees nothing and
                # log_activity would discard the whole updated entry as a no-op.
                changes.append(
                    Change(
                        type="DataWarehouseSavedQuery",
                        action="changed",
                        field="sync_frequency_interval",
                        before=str(previous_target) if previous_target is not None else None,
                        after=str(target) if target is not None else None,
                    )
                )
            activity_log = log_activity(
                organization_id=team.organization_id,
                team_id=team.id,
                user=self.context["request"].user,
                was_impersonated=is_impersonated(self.context["request"]),
                item_id=view.id,
                scope="DataWarehouseSavedQuery",
                activity="updated",
                detail=Detail(name=view.name, changes=changes),
            )

            # Store the activity log in the serializer context
            if activity_log:
                self.context["activity_log"] = activity_log
            else:
                # get latest query-changing activity log for this model (see QUERY_CHANGE_ACTIVITY_FILTER)
                latest_activity_log = (
                    ActivityLog.objects.filter(
                        team_id=locked_instance.team_id,
                        item_id=locked_instance.id,
                        scope="DataWarehouseSavedQuery",
                        **QUERY_CHANGE_ACTIVITY_FILTER,
                    )
                    .order_by("-created_at")
                    .first()
                )
                self.context["activity_log"] = latest_activity_log
        # best effort sync to new data modeling DAG representation
        if "query" in validated_data:
            try:
                from products.data_modeling.backend.facade.api import sync_saved_query_to_dag
                from products.data_modeling.backend.facade.models import DAG

                dag_obj = None
                if dag_id:
                    dag_obj = DAG.objects.filter(id=dag_id, team_id=view.team_id).first()
                sync_saved_query_to_dag(view, dag=dag_obj)
            except Exception as e:
                capture_exception(e)
                logger.exception("Failed to sync saved query to DAG", saved_query_name=view.name)
        return view

    def validate_query(self, query):
        if not isinstance(query, dict):
            raise exceptions.ValidationError(
                detail=(
                    'Query must be a JSON object with a "query" key, '
                    f"got {type(query).__name__}. "
                    'Example: {"kind": "HogQLQuery", "query": "SELECT * FROM events WHERE timestamp >= now() - INTERVAL 7 DAY LIMIT 100"}'
                )
            )
        if not isinstance(query.get("query"), str) or not query["query"].strip():
            raise exceptions.ValidationError(
                detail='Query object must contain a non-empty "query" key with the SQL string.'
            )

        team_id = self.context["team_id"]
        user = self.context["request"].user

        context = HogQLContext(team_id=team_id, user=user, enable_select_queries=True)
        try:
            select_ast = parse_select(query["query"])

            find_placeholders = FindPlaceholders()
            find_placeholders.visit(select_ast)
        except ExposedHogQLError as err:
            raise exceptions.ValidationError(detail=f"Invalid query: {err}")
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

    def validate(self, attrs):
        attrs = super().validate(attrs)

        # Falls back to the stored config so editing the query of an already-incremental view is
        # checked too. Otherwise a query that incremental cannot serve would save while the view
        # stays incremental, and only fail at the next run.
        config = attrs.get("incremental_config")
        if config is None and self.instance is not None:
            config = self.instance.incremental_config
        if not isinstance(config, dict) or not config.get("enabled"):
            return attrs
        if not config.get("incremental_key") or not config.get("unique_key"):
            return attrs

        query_changed = "query" in attrs
        query = attrs.get("query") or (self.instance.query if self.instance is not None else None)
        sql = (query or {}).get("query")
        if not isinstance(sql, str):
            raise serializers.ValidationError({"incremental": "This view has no query to make incremental."})

        from products.data_modeling.backend.facade.api import IncrementalConfig, check_incremental_eligibility

        # The stored column types describe the stored query, so they say nothing about a query being
        # replaced. The runtime guard still catches a nullable key on the first incremental run.
        column_types = None if query_changed or self.instance is None else self.instance.columns
        # The context only carries a database when the request touches the query or name; a
        # config-only PATCH still has to check `SELECT *` against real columns, so build one then.
        database = self.context.get("database") or Database.create_for(
            team_id=self.context["team_id"], user=cast(User, self.context["request"].user)
        )
        result = check_incremental_eligibility(
            sql,
            IncrementalConfig(
                incremental_key=config["incremental_key"],
                unique_key=tuple(config["unique_key"]),
                lookback_seconds=config.get("lookback_seconds", 0),
            ),
            column_types=_clickhouse_types(column_types),
            database=database,
        )
        if not result.eligible:
            raise serializers.ValidationError({"incremental": result.blockers})
        return attrs

    def validate_is_test(self, is_test):
        if is_test and not self.context["request"].user.is_staff:
            raise serializers.ValidationError("Only staff users can create test views.")
        return is_test

    def validate_folder(self, folder):
        if folder is not None and folder.team_id != self.context["team_id"]:
            raise serializers.ValidationError("Folder not found.")
        return folder

    def validate_name(self, name):
        # if it's an upsert, we don't want to validate the name
        if self.instance is not None and isinstance(self.instance, DataWarehouseSavedQuery):
            if self.instance.name == name:
                return name

        # has_table covers system/posthog tables and warehouse objects the requesting user can see; it's
        # user-filtered, so also resolve the name team-wide using get_view_or_table_by_name.
        # Otherwise a user with denied table could create another one with colliding name.
        if self.context["database"].has_table(name) or get_view_or_table_by_name(self.context["team_id"], name):
            raise serializers.ValidationError("A table or view with this name already exists. Choose a different name.")

        return name


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


class SavedQueryLineageRequestSerializer(serializers.Serializer):
    """Body of the `ancestors` and `descendants` actions."""

    level = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="How many hops to walk, so 1 gives the immediate neighbours. Omit to walk the whole cone.",
    )


class SavedQueryAncestorsSerializer(serializers.Serializer):
    ancestors = serializers.ListField(
        child=serializers.CharField(),
        help_text="Ids of the saved queries and warehouse tables this query reads from, directly or "
        "through other queries, and the names of the PostHog tables among them.",
    )


class SavedQueryDescendantsSerializer(serializers.Serializer):
    descendants = serializers.ListField(
        child=serializers.CharField(),
        help_text="Ids of the saved queries that read from this query, directly or through other queries.",
    )


class SavedQueryDependenciesSerializer(serializers.Serializer):
    upstream_count = serializers.IntegerField(help_text="How many tables and queries this query reads from directly.")
    downstream_count = serializers.IntegerField(help_text="How many queries read from this query directly.")


class IncrementalEligibilitySerializer(serializers.Serializer):
    """Whether a query can be materialized incrementally, and what stands in the way."""

    eligible = serializers.BooleanField(help_text="True when nothing blocks incremental materialization.")
    key_candidates = serializers.ListField(
        child=serializers.CharField(),
        help_text="Output columns that could be used as the incremental key. Excludes aggregates, "
        "columns whose type cannot serve as an advancing watermark (strings, booleans, arrays), "
        "and for a union only includes columns every branch produces.",
    )
    unique_key_candidates = serializers.ListField(
        child=serializers.CharField(),
        help_text="Output columns the unique key may be built from. A superset of key_candidates: "
        "identifying a row only needs equality, so strings qualify here even though they cannot "
        "be the incremental key.",
    )
    key_candidate_types = serializers.DictField(
        child=serializers.CharField(),
        help_text="Coarse type per candidate, keyed by column name: datetime, date, integer, "
        "decimal, float, string, or uuid. A candidate with no entry has a type the check could "
        "not determine.",
    )
    blockers = serializers.ListField(
        child=serializers.CharField(),
        help_text="Reasons this query cannot be incremental. Each names the construct responsible.",
    )
    warnings = serializers.ListField(
        child=serializers.CharField(),
        help_text="Things that still work but are worth knowing, such as a filter that cannot be "
        "pushed down so each run reads as much data as a full refresh.",
    )


# Same bound other SQL-accepting endpoints put on caller-supplied queries (see
# `posthog/api/query_performance_proxy.py`): parsing runs synchronously on an API worker, so the
# body has to be capped before it reaches the parser.
CHECK_INCREMENTAL_MAX_QUERY_LENGTH = 64 * 1024


class CheckIncrementalThrottle(PersonalApiKeyOrUserRateThrottle):
    """check_incremental parses caller-supplied SQL synchronously on a read scope. The editor calls
    it on a debounce, so a per-caller budget far above typing speed only stops scripted floods of
    large bodies from tying up API workers."""

    scope = "check_incremental"
    rate = "120/minute"


class CheckIncrementalSerializer(serializers.Serializer):
    """Body of the `check_incremental` action: a query and an optional config to check it against."""

    query = serializers.CharField(max_length=CHECK_INCREMENTAL_MAX_QUERY_LENGTH, help_text="The HogQL query to check.")
    incremental_key = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Output column whose advancing value marks rows as new. Omit to only list candidates.",
    )
    unique_key = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        help_text="Output columns that identify a row. Must include every GROUP BY column.",
    )
    lookback_seconds = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=MAX_LOOKBACK_SECONDS,
        help_text="How far back before the watermark to re-read each run, to pick up late-arriving data.",
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

    sync_frequency = frequency.SyncFrequencyField(
        choices=frequency.MATERIALIZE_SYNC_FREQUENCY_CHOICES,
        allow_null=False,
        default=frequency.DEFAULT_MATERIALIZE_SYNC_FREQUENCY,
        help_text=(
            "How often to refresh the materialized table, defaulting to daily. Rejected with a 400 when it falls "
            "outside what the query's lineage allows: no more often than its sources deliver new data, and no less "
            "often than a downstream view or endpoint needs."
        ),
    )
