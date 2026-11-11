"""The writable saved-query serializer: validation, create, and update."""

import copy
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any, TypedDict, cast

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog
from drf_spectacular.utils import extend_schema_field
from rest_framework import exceptions, serializers

from posthog.schema import ExecutionTarget, HogQLQuery

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import (
    MODELS_NAMESPACE_QUERY_ERROR,
    Database,
    is_reserved_models_name,
    models_namespace_chain,
)
from posthog.hogql.direct_sql.trino_adapter import ensure_read_only_raw_trino_statement
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.metadata import get_table_names
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import FindPlaceholders
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.resolver import resolve_types

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer
from posthog.errors import ExposedCHQueryError, QueryErrorCategory, classify_query_error
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.helpers.impersonation import is_impersonated
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, changes_between, log_activity
from posthog.rbac.query_access import assert_user_can_read_query

from products.access_control.backend.presentation.access_control import UserAccessControlSerializerMixin
from products.data_modeling.backend.facade import api as modeling_api
from products.data_modeling.backend.facade.api import has_incremental_history
from products.data_modeling.backend.facade.modeling import ResolutionCycleError, get_parents_from_model_query
from products.data_modeling.backend.facade.models import (
    CONNECTION_SAVE_REASON,
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryColumnAnnotation,
    ViewColumnSource,
    ViewEngine,
    ViewEngineTarget,
    validate_saved_query_name,
)
from products.data_tools.backend.facade.models import DataWarehouseSavedQueryFolder
from products.data_warehouse.backend.presentation.views.column_annotation_base import upsert_annotation
from products.managed_warehouse.backend.facade.query_execution import validate_managed_trino_query
from products.warehouse_sources.backend.facade.hogql import (
    get_view_or_table_by_name,
    hogql_type_name_for_clickhouse_type,
)
from products.warehouse_sources.backend.facade.models import sync_frequency_to_sync_frequency_interval

from . import incremental_config, sync_cadence, view_description, view_state

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

logger = structlog.get_logger(__name__)

GENERIC_LINEAGE_SYNC_ERROR = (
    "Could not build this view's lineage. Check the query's tables and columns, then save again."
)
BREAKING_COLUMN_CHANGE_CODE = "breaking_column_change"
MAX_NAMED_AFFECTED_VIEWS = 3


class BreakingColumnChange(TypedDict):
    removed_columns: tuple[str, ...]
    affected_view_names: tuple[str, ...]
    visible_affected_view_count: int
    total_affected_view_count: int
    has_hidden_affected_views: bool


class BreakingColumnChangeError(serializers.ValidationError):
    def __init__(self, change: BreakingColumnChange) -> None:
        super().__init__(
            "This change removes columns that downstream views use. Save again to confirm the change.",
            code=BREAKING_COLUMN_CHANGE_CODE,
        )
        self.extra = {
            "removed_columns": change["removed_columns"],
            "affected_views": change["affected_view_names"][:MAX_NAMED_AFFECTED_VIEWS],
            "affected_view_count": change["visible_affected_view_count"],
            "has_hidden_affected_views": change["has_hidden_affected_views"],
        }


def _lineage_sync_error_detail(error: Exception) -> str:
    # The marker is served verbatim by the node API, so only a message written for the user may reach it.
    return str(error) if isinstance(error, ExposedHogQLError) else GENERIC_LINEAGE_SYNC_ERROR


def _columns_from_client_types(client_types: list[list[str]]) -> dict[str, dict[str, Any]]:
    return {
        str(item[0]): {
            "hogql": hogql_type_name_for_clickhouse_type(str(item[1])),
            "clickhouse": item[1],
            "valid": True,
        }
        for item in client_types
    }


def _capture_unless_user_error(error: Exception) -> None:
    # Errors in the user's own SQL are not defects. Classify by error code, not by class, because
    # some user-safe ClickHouse codes, for example UNKNOWN_IDENTIFIER, are not ExposedCHQueryError.
    if classify_query_error(error) != QueryErrorCategory.USER_ERROR:
        capture_exception(error)


def _as_uuid(value: object) -> uuid.UUID | None:
    # Clients echo the revision back in whatever UUID form their stack produces, so parse both
    # sides before comparing. A raw string comparison rejects an uppercase or unhyphenated spelling
    # of the same revision as a foreign edit.
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return None


def _view_types_validation_error(e: Exception) -> serializers.ValidationError:
    # Column inference runs the HogQL-to-ClickHouse path, so a raw exception can carry stack
    # traces, internal table or column names, and S3 URIs. Surface only the errors already marked
    # user-safe; reduce everything else to its class name. Mirrors validate_query below, which
    # keeps the full cause in error tracking and logs instead of the response.
    if isinstance(e, ExposedHogQLError | ExposedCHQueryError):
        return serializers.ValidationError(f"Failed to retrieve types for view: {e}")
    return serializers.ValidationError(f"Failed to retrieve types for view: unexpected {type(e).__name__}")


def _unreferenceable_view_refusal(team_id: int, sql: str) -> str | None:
    """Why `sql` fails to resolve, when it names a saved view that HogQL on ClickHouse cannot reference.

    The HogQL database leaves such views out, so without this the refusal only says the table is unknown.
    """
    try:
        names = get_table_names(parse_select(sql))
    except ExposedHogQLError:
        return None
    views = (
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, name__in=names)
        .exclude(deleted=True)
        .only("name", "query")
        .order_by("name")
    )
    for view in views:
        reference = view.engine.referenceable_from_clickhouse
        if not reference.available:
            return f"This view reads '{view.name}'. {reference.reason} Remove that reference to save this view."
    return None


def _apply_frequency_target(
    view: DataWarehouseSavedQuery,
    frequency: str | None,
    user_access_control: "UserAccessControl | None",
) -> timedelta | None:
    target = sync_frequency_to_sync_frequency_interval(frequency) if frequency else None
    # A refusal names what blocks the cadence, so it obeys the same grants the read
    # payload does — otherwise one rejected PATCH reads back a name the caller was
    # never shown. Withheld nodes fall back to generic prose inside the refusal.
    bounds = modeling_api.saved_query_target_bounds(view.team_id, view.pk)
    visible = (
        sync_cadence.visible_blocker_names(bounds, user_access_control, team_id=view.team_id)
        if bounds is not None
        else {}
    )
    try:
        # Validate before commit so a rejected frequency rolls back the write.
        nodes_written = modeling_api.apply_saved_query_frequency_target(view, target, visible_names=visible)
    except (modeling_api.UnsatisfiableFrequencyError, modeling_api.UnsupportedFrequencyTargetError) as e:
        raise serializers.ValidationError(str(e))
    if target is not None and nodes_written == 0:
        raise serializers.ValidationError(
            "Cannot set a materialization frequency: this view is not wired into the data "
            "modeling DAG yet. Re-save the view to create its node, then set the frequency."
        )
    return target


def _cadence_asks_to_materialize(view: DataWarehouseSavedQuery, sync_frequency: str | None) -> bool:
    # Incremental only means something for a materialized table, so a cadence on an incremental
    # view asks for one. Without a cadence the caller materializes it, as the SQL editor does.
    return (
        view.engine.can_materialize.available
        and not view.is_materialized
        and sync_frequency not in (None, "never")
        and bool((view.incremental_config or {}).get("enabled"))
    )


def _authored_model_answering_to(
    team_id: int, name: str, exclude: DataWarehouseSavedQuery | None
) -> DataWarehouseSavedQuery | None:
    if not name.startswith("models."):
        return None
    candidates = DataWarehouseSavedQuery.objects.filter(team_id=team_id, name=name.removeprefix("models.")).exclude(
        deleted=True
    )
    if exclude is not None:
        candidates = candidates.exclude(pk=exclude.pk)
    return next((query for query in candidates if models_namespace_chain(query) == name.split(".")), None)


INCREMENTAL_CONFIG_CHANGED_REFUSAL = (
    "This view's incremental settings changed while you were editing it. Reload the view and try again."
)


class DataWarehouseSavedQuerySerializer(
    view_state.DataWarehouseSavedQuerySerializerMixin, UserAccessControlSerializerMixin, serializers.ModelSerializer
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
    sync_frequency = sync_cadence.SyncFrequencyField(
        help_text=(
            "How often to materialize this view. One of '15min', '30min', '1hour', '6hour', '12hour', "
            "'24hour', '7day', '30day', or 'never' to pause scheduled materialization. 15min is the fastest "
            "cadence available. Null means no scheduled materialization. Read back after a write, this "
            "reflects the cadence stored on the view's DAG node."
        ),
    )
    sync_frequency_bounds = serializers.SerializerMethodField(
        read_only=True, help_text=sync_cadence.SYNC_FREQUENCY_BOUNDS_HELP_TEXT
    )
    latest_history_id = serializers.UUIDField(
        source="query_revision",
        read_only=True,
        allow_null=True,
        help_text="Revision of this view's query. Send it back as edited_history_id on the next query "
        "write, so conflict detection can tell whether someone else changed the query in the meantime. "
        "Edits that leave the query alone do not advance it.",
    )
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
        help_text="The latest_history_id you last read for this view. Required when changing the query. "
        "The write is refused if someone else changed the query in the meantime.",
    )
    soft_update = serializers.BooleanField(
        write_only=True,
        required=False,
        allow_null=True,
        help_text="If true, skip column inference and external table discovery. On update, also skip the query "
        "revision conflict check. Query validation and revision updates still run.",
    )
    acknowledge_breaking_changes = serializers.BooleanField(
        write_only=True,
        required=False,
        default=False,
        help_text="Confirm an update that removes columns used by downstream views. The first request is refused "
        "with code 'breaking_column_change' and names the affected views that the caller can access.",
    )
    description = view_description.ViewDescriptionField(
        required=False, allow_blank=True, allow_null=True, help_text=view_description.VIEW_DESCRIPTION_HELP_TEXT
    )
    incremental = incremental_config.IncrementalConfigSerializer(
        source="incremental_config",
        required=False,
        allow_null=True,
        help_text="Update the materialized table in place instead of rebuilding it. Null or absent "
        "means every run rebuilds the whole table.",
    )
    incremental_state = incremental_config.IncrementalStateSerializer(
        read_only=True,
        allow_null=True,
        help_text="How far incremental materialization has progressed. Null until the first run "
        "records any. Written by the materialization run, not by this API.",
    )
    has_incremental_history = serializers.SerializerMethodField(
        help_text="Whether incremental settings participated in any materialization run."
    )
    engine = view_state.ViewEngineSerializer(read_only=True, help_text=view_state.VIEW_ENGINE_HELP_TEXT)

    class Meta:
        model = DataWarehouseSavedQuery
        fields = [
            "id",
            "deleted",
            "name",
            "query",
            "incremental",
            "incremental_state",
            "has_incremental_history",
            "created_by",
            "created_at",
            "updated_at",
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
            "acknowledge_breaking_changes",
            "is_materialized",
            "origin",
            "is_test",
            "expires_at",
            "user_access_level",
            "suspended",
            "engine",
        ]
        read_only_fields = [
            "id",
            # Deletion must run lifecycle cleanup and release the name through DELETE.
            "deleted",
            "created_by",
            "created_at",
            "updated_at",
            "columns",
            "incremental_state",
            "has_incremental_history",
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
                "validators": [],
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

    @extend_schema_field(serializers.BooleanField())
    def get_has_incremental_history(self, view: DataWarehouseSavedQuery) -> bool:
        return has_incremental_history(view)

    def _report_view_action(
        self, event: str, view: DataWarehouseSavedQuery, properties: dict[str, Any], team: Team
    ) -> None:
        if (
            not self.context.get("report_view_actions", False)
            or view.origin in {DataWarehouseSavedQuery.Origin.ENDPOINT, DataWarehouseSavedQuery.Origin.MANAGED_VIEWSET}
            or view.managed_viewset_id is not None
        ):
            return

        request = self.context["request"]
        try:
            report_user_action(
                request.user,
                event,
                {
                    # Never include the query text or the view name: both are customer-authored content.
                    "saved_query_id": str(view.id),
                    "origin": view.origin,
                    "is_materialized": bool(view.is_materialized),
                    "has_warehouse_tables": bool(view.external_tables),
                    **properties,
                },
                team=team,
                request=request,
            )
        except Exception as e:
            capture_exception(e)
            logger.exception("Failed to report view action", analytics_event=event)

    def _columns_from_request_types(self) -> dict[str, dict[str, Any]]:
        client_types = self.context["request"].data.get("types", [])
        if not isinstance(client_types, list) or any(
            not isinstance(item, list | tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], str)
            for item in client_types
        ):
            raise serializers.ValidationError('"types" must be a list of [column name, column type] string pairs.')
        if len(client_types) == 0:
            raise serializers.ValidationError("Run the query in the SQL editor before saving it as a view.")
        return _columns_from_client_types(client_types)

    def _materialize(self, view: DataWarehouseSavedQuery, sync_frequency: str) -> None:
        request = self.context["request"]
        try:
            modeling_api.enable_saved_query_materialization(
                view.team_id,
                view.id,
                user=cast(User, request.user),
                frequency_target=sync_frequency_to_sync_frequency_interval(sync_frequency),
                visible_blocker_names=lambda bounds: sync_cadence.visible_blocker_names(
                    bounds, self.user_access_control, team_id=view.team_id
                ),
                was_impersonated=is_impersonated(request),
            )
        except modeling_api.MaterializationForbiddenError as e:
            raise exceptions.PermissionDenied(str(e))
        except modeling_api.MaterializationRefusedError as e:
            raise serializers.ValidationError(str(e))
        except modeling_api.MaterializationFailedError as e:
            raise exceptions.APIException(str(e))
        view.refresh_from_db()

    def _validate_view_dependencies(self, team: Team, name: str, query: str) -> None:
        try:
            get_parents_from_model_query(team, name, query, database=self.context["database"])
        except (RecursionError, ResolutionCycleError):
            raise serializers.ValidationError("Model contains a cycle")
        except Exception as error:
            refusal = _unreferenceable_view_refusal(team.pk, query)
            if refusal is not None:
                raise serializers.ValidationError(refusal)
            _capture_unless_user_error(error)
            raise _view_types_validation_error(error)

    @staticmethod
    def _resolved_output_columns(view: DataWarehouseSavedQuery, database: Database) -> set[str] | None:
        context = HogQLContext(
            team=view.team,
            team_id=view.team_id,
            enable_select_queries=True,
            database=database,
            # This internal comparison must inspect every dependent. Names are filtered by access control below.
            bypass_warehouse_access_control=True,
        )
        try:
            resolved = resolve_types(parse_select(view.sql), context, dialect="clickhouse")
        except Exception:
            return None
        if not isinstance(resolved.type, (ast.SelectQueryType, ast.SelectSetQueryType)):
            return set()
        return set(resolved.type.columns)

    def _breaking_column_change(
        self,
        instance: DataWarehouseSavedQuery,
        pending_query: dict[str, Any],
        inferred_columns: dict[str, dict[str, Any]],
    ) -> BreakingColumnChange | None:
        removed_columns = tuple(sorted(set(instance.columns or {}) - set(inferred_columns)))
        if not removed_columns:
            return None

        dependent_ids = modeling_api.dependent_saved_query_ids(instance.team_id, [instance.id]).get(
            instance.id, frozenset()
        )
        if not dependent_ids:
            return None

        dependents = list(
            DataWarehouseSavedQuery.objects.filter(team_id=instance.team_id, id__in=dependent_ids)
            .exclude(deleted=True)
            .order_by("name", "id")
        )
        # Dependency validation must not depend on which downstream views the editor can open.
        database = Database.create_for(team=instance.team, bypass_warehouse_access_control=True)
        current_outputs = {
            dependent.id: output
            for dependent in dependents
            if (output := self._resolved_output_columns(dependent, database)) is not None
        }

        pending = copy.copy(instance)
        pending.query = pending_query
        pending.set_columns(inferred_columns)
        table_node = database.get_table_node(instance.name_chain)
        current_table = table_node.table
        table_node.table = pending.hogql_definition()
        try:
            affected = [
                dependent
                for dependent in dependents
                if dependent.id in current_outputs
                and (
                    (pending_output := self._resolved_output_columns(dependent, database)) is None
                    or bool(current_outputs[dependent.id] - pending_output)
                )
            ]
        finally:
            table_node.table = current_table

        if not affected:
            return None

        affected_ids = [dependent.id for dependent in affected]
        visible_ids = (
            modeling_api.allowed_saved_query_ids(
                instance.team_id,
                self.user_access_control,
                ids=affected_ids,
            )
            if self.user_access_control is not None
            else frozenset()
        )
        visible_names = tuple(dependent.name for dependent in affected if dependent.id in visible_ids)
        return BreakingColumnChange(
            removed_columns=removed_columns,
            affected_view_names=visible_names,
            visible_affected_view_count=len(visible_names),
            total_affected_view_count=len(affected),
            has_hidden_affected_views=len(visible_names) < len(affected),
        )

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        validated_data["origin"] = DataWarehouseSavedQuery.Origin.DATA_WAREHOUSE
        soft_update = validated_data.pop("soft_update", False)
        has_description = "description" in validated_data
        description = validated_data.pop("description", None)
        sync_frequency = validated_data.pop("sync_frequency", None)
        validated_data.pop("edited_history_id", None)
        validated_data.pop("acknowledge_breaking_changes", None)
        view = DataWarehouseSavedQuery(**validated_data)
        engine = view.engine

        if sync_frequency not in (None, "never") and not engine.can_materialize.available:
            raise serializers.ValidationError(engine.can_materialize.reason)
        if engine.column_source == ViewColumnSource.CLIENT_TYPES:
            view.set_columns(self._columns_from_request_types())
        if engine.has_lineage.available:
            self._validate_view_dependencies(self.context["get_team"](), view.name, validated_data["query"]["query"])

        if not soft_update and engine.column_source == ViewColumnSource.CLICKHOUSE_PROBE:
            try:
                # The columns will be inferred from the query
                client_types = self.context["request"].data.get("types", [])
                if len(client_types) == 0:
                    view.set_columns(view.get_columns(user=self.context["request"].user))
                else:
                    view.set_columns(_columns_from_client_types(client_types))

                view.external_tables = view.get_s3_tables(database=self.context["database"])
            except Exception as e:
                _capture_unless_user_error(e)
                logger.exception("Failed to retrieve types for view %s", view.name)
                raise _view_types_validation_error(e)

        with transaction.atomic():
            view.save()
            if has_description:
                self._write_view_description(view, description)
            team = Team.objects.get(id=view.team_id)

            log_activity(
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
            if engine.has_lineage.available:
                try:
                    with transaction.atomic():
                        modeling_api.sync_saved_query_to_dag(view)
                except Exception as e:
                    capture_exception(e)
                    logger.exception("Failed to sync saved query to DAG", saved_query_name=view.name)
                    modeling_api.adopt_saved_query_without_edges(view.team_id, view.id, _lineage_sync_error_detail(e))
            # The frequency writes through to the DAG node's freshness target, which only a view with lineage has.
            if sync_frequency is not None and engine.has_lineage.available:
                if sync_frequency != "never":
                    assert_user_can_read_query(
                        view.query,
                        view.team_id,
                        cast(User, self.context["request"].user),
                        database=self.context.get("database"),
                    )
                _apply_frequency_target(view, sync_frequency, self.user_access_control)

        if _cadence_asks_to_materialize(view, sync_frequency):
            # After commit, so the first run the schedule starts can read the new row.
            self._materialize(view, sync_frequency)

        self._report_view_action(
            "view created",
            view,
            {"has_description": has_description, "sync_frequency": sync_frequency},
            team,
        )
        return view

    def update(self, instance: Any, validated_data: Any) -> Any:
        has_description = "description" in validated_data
        description = validated_data.pop("description", None)

        if instance.managed_viewset is not None:
            raise serializers.ValidationError("Cannot update a query from a managed viewset")

        frequency_given = "sync_frequency" in validated_data
        sync_frequency = validated_data.pop("sync_frequency", None)
        engine = ViewEngine.from_query(validated_data.get("query", instance.query))

        if sync_frequency not in (None, "never") and not engine.can_materialize.available:
            raise serializers.ValidationError(engine.can_materialize.reason)

        if sync_frequency and sync_frequency != "never":
            # Scheduling a view is the same grant as materializing it directly.
            assert_user_can_read_query(
                instance.query,
                self.context["team_id"],
                cast(User, self.context["request"].user),
                database=self.context.get("database"),
            )

        # Setting a cadence needs the view's DAG node. Clearing one does not, because a direct-connection view
        # saved before those views lost lineage can still hold a node target that a pause must remove.
        frequency_changed = frequency_given and (engine.has_lineage.available or sync_frequency in (None, "never"))

        soft_update = validated_data.pop("soft_update", False)
        acknowledge_breaking_changes = validated_data.pop("acknowledge_breaking_changes", False)
        edited_history_id = self.context["request"].data.get("edited_history_id", None)
        check_conflict = (
            "query" in validated_data
            and validated_data["query"] != instance.query
            and not soft_update
            and instance.query_revision is not None
        )

        if check_conflict and _as_uuid(edited_history_id) != instance.query_revision:
            # Advisory only: rejects a stale edit before it pays for inference. The check under the
            # row lock below is the one that prevents a lost update.
            raise serializers.ValidationError("The query was modified by someone else.")

        inferred_columns: dict[str, dict[str, Any]] | None = None
        inferred_external_tables: list[str] | None = None
        # Switching would add or drop the view's DAG node, and the dependents that read it through HogQL.
        if engine.has_lineage.available != instance.engine.has_lineage.available:
            raise serializers.ValidationError(
                "A view cannot switch to or from raw Trino SQL or a direct connection. Save it as a new view."
            )
        if engine.column_source == ViewColumnSource.CLIENT_TYPES and "query" in validated_data and not soft_update:
            inferred_columns = self._columns_from_request_types()
            inferred_external_tables = []
        if engine.has_lineage.available and ("query" in validated_data or "name" in validated_data):
            self._validate_view_dependencies(
                instance.team,
                validated_data.get("name", instance.name),
                validated_data.get("query", instance.query)["query"],
            )
        if "query" in validated_data and not soft_update and engine.column_source == ViewColumnSource.CLICKHOUSE_PROBE:
            # Inference runs the query on ClickHouse, so it happens before the row lock, on a probe
            # carrying the pending query and name rather than the stored ones, as create() does.
            probe = DataWarehouseSavedQuery(
                team=instance.team,
                name=validated_data.get("name", instance.name),
                query=validated_data["query"],
            )
            try:
                client_types = self.context["request"].data.get("types", [])
                if len(client_types) == 0:
                    inferred_columns = probe.get_columns(user=self.context["request"].user)
                else:
                    inferred_columns = _columns_from_client_types(client_types)
                inferred_external_tables = probe.get_s3_tables(database=self.context["database"])
            except (RecursionError, ResolutionCycleError):
                raise serializers.ValidationError("Model contains a cycle")
            except Exception as e:
                _capture_unless_user_error(e)
                logger.exception("Failed to retrieve types for view %s", probe.name)
                raise _view_types_validation_error(e)

        breaking_column_change = None
        if inferred_columns is not None and "query" in validated_data:
            breaking_column_change = self._breaking_column_change(instance, validated_data["query"], inferred_columns)
            if breaking_column_change is not None and not acknowledge_breaking_changes:
                raise BreakingColumnChangeError(breaking_column_change)

        with transaction.atomic():
            try:
                # `FOR NO KEY UPDATE`, not `FOR UPDATE`: this lock is held across a DAG lock, and
                # `FOR UPDATE` conflicts with the `KEY SHARE` lock a concurrent materialization
                # takes on this row for its job's foreign key, which deadlocks the two. It still
                # blocks every other writer of the row, which is all the lost-update check needs.
                locked_instance = (
                    DataWarehouseSavedQuery.objects.select_for_update(no_key=True)
                    .exclude(deleted=True)
                    .get(pk=instance.pk)
                )
            except DataWarehouseSavedQuery.DoesNotExist:
                raise exceptions.NotFound("Not found.")
            before_update = copy.copy(locked_instance)

            query_changed = "query" in validated_data and validated_data["query"] != locked_instance.query

            if query_changed and not soft_update and locked_instance.query_revision is not None:
                if _as_uuid(edited_history_id) != locked_instance.query_revision:
                    raise serializers.ValidationError("The query was modified by someone else.")

            if (
                query_changed
                and "incremental_config" not in validated_data
                and locked_instance.incremental_config != instance.incremental_config
            ):
                raise serializers.ValidationError(INCREMENTAL_CONFIG_CHANGED_REFUSAL)

            if query_changed:
                validated_data["query_revision"] = uuid.uuid4()
                validated_data["query_updated_at"] = timezone.now()

            view: DataWarehouseSavedQuery = super().update(locked_instance, validated_data)
            name_changed = before_update.name != view.name

            if frequency_changed:
                previous_target = modeling_api.declared_targets_by_saved_query(view.team_id, [view.pk]).get(
                    str(view.pk)
                )
                target = _apply_frequency_target(view, sync_frequency, self.user_access_control)

            if has_description:
                self._write_view_description(view, description)

            if inferred_columns is not None:
                columns_changed = not before_update.stores_columns(inferred_columns)
                view.set_columns(inferred_columns)
                view.external_tables = inferred_external_tables
                view.status = DataWarehouseSavedQuery.Status.MODIFIED
                view.save()
                if columns_changed:
                    modeling_api.schedule_downstream_view_column_refresh(
                        view.team_id, view.id, self.context["request"].user.id
                    )

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
                changes.extend(modeling_api.cadence_changes((previous_target, target)))
            log_activity(
                organization_id=team.organization_id,
                team_id=team.id,
                user=self.context["request"].user,
                was_impersonated=is_impersonated(self.context["request"]),
                item_id=view.id,
                scope="DataWarehouseSavedQuery",
                activity="updated",
                detail=Detail(name=view.name, changes=changes),
            )

            # Best effort sync to the data modeling DAG representation. The savepoint keeps a
            # failed sync best effort without poisoning the update's own transaction.
            if ("query" in validated_data or name_changed) and view.engine.has_lineage.available:
                try:
                    with transaction.atomic():
                        modeling_api.sync_saved_query_to_dag(view)
                except Exception as e:
                    capture_exception(e)
                    logger.exception("Failed to sync saved query to DAG", saved_query_name=view.name)
                    modeling_api.adopt_saved_query_without_edges(view.team_id, view.id, _lineage_sync_error_detail(e))

        if frequency_changed and _cadence_asks_to_materialize(view, sync_frequency):
            self._materialize(view, sync_frequency)

        self._report_view_action(
            "view updated",
            view,
            {
                "query_changed": query_changed,
                "name_changed": before_update.name != view.name,
                "description_changed": has_description,
                "sync_frequency": sync_frequency if frequency_changed else None,
                "soft_update": soft_update,
                "breaking_column_change_acknowledged": bool(
                    breaking_column_change is not None and acknowledge_breaking_changes
                ),
                "removed_column_count": (
                    len(breaking_column_change["removed_columns"]) if breaking_column_change is not None else 0
                ),
                "affected_downstream_view_count": (
                    breaking_column_change["total_affected_view_count"] if breaking_column_change is not None else 0
                ),
            },
            team,
        )
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
        engine = ViewEngine.from_query(query)

        # Saved connection views stay as they are; this only blocks writing a connection query.
        if engine.target == ViewEngineTarget.CONNECTION:
            raise exceptions.ValidationError(detail=CONNECTION_SAVE_REASON)

        if engine.is_raw_trino:
            try:
                validate_managed_trino_query(
                    HogQLQuery(query=query["query"], executionTarget=ExecutionTarget.MANAGED_TRINO, sendRawQuery=True),
                    self.context["get_team"](),
                    user,
                )
                ensure_read_only_raw_trino_statement(query["query"])
            except ExposedHogQLError as err:
                raise exceptions.ValidationError(detail=f"Invalid query: {err}")
            return query

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
                refusal = _unreferenceable_view_refusal(team_id, query["query"])
                raise exceptions.ValidationError(detail=refusal or f"Invalid query: {err}")
            elif not settings.DEBUG:
                # We don't want to accidentally expose too much data via errors
                raise exceptions.ValidationError(detail=f"Unexpected {err.__class__.__name__}")

        return query

    def is_valid(self, *, raise_exception: bool = False) -> bool:
        try:
            return super().is_valid(raise_exception=raise_exception)
        except serializers.ValidationError as error:
            # DRF rebuilds the error raised in validate(), so the refused keys are attached here.
            # drf-exceptions-hog renders `extra` into the response, and the editor reads
            # `extra.blocked_keys` to show the error under the field it names.
            refused_keys = getattr(self, "_refused_incremental_keys", None)
            if refused_keys:
                error.extra = {"blocked_keys": refused_keys}  # type: ignore[attr-defined]
            raise

    def validate(self, attrs):
        attrs = super().validate(attrs)

        # Falls back to the stored config so editing the query of an already-incremental view is
        # checked too. Otherwise a query that incremental cannot serve would save while the view
        # stays incremental, and only fail at the next run.
        config = attrs.get("incremental_config")
        if config is None and self.instance is not None:
            config = self.instance.incremental_config
        incremental = isinstance(config, dict) and bool(config.get("enabled"))

        query_changed = "query" in attrs or self.instance is None
        output_columns = self._pending_output_columns(query_changed)
        if output_columns is not None and self._changes_what_materializes(attrs, incremental):
            duplicates = modeling_api.duplicate_output_columns(name for name, _ in output_columns)
            if duplicates:
                raise serializers.ValidationError({"query": modeling_api.duplicate_output_columns_message(duplicates)})

        if not incremental or not isinstance(config, dict):
            return attrs
        if not config.get("incremental_key") or not config.get("unique_key"):
            return attrs

        query = attrs.get("query") or (self.instance.query if self.instance is not None else None)
        sql = (query or {}).get("query")
        if not isinstance(sql, str):
            raise serializers.ValidationError({"incremental": "This view has no query to make incremental."})

        from products.data_modeling.backend.facade.api import (
            IncrementalConfig,
            check_incremental_eligibility,
            definition_database,
        )

        # Without column types the nullable key check is skipped, and the runtime guard catches a
        # nullable key on the first incremental run instead.
        column_types = {name: clickhouse_type for name, clickhouse_type in output_columns or [] if clickhouse_type}
        database = definition_database(self.context["team_id"], user=cast(User, self.context["request"].user))
        result = check_incremental_eligibility(
            sql,
            IncrementalConfig(
                incremental_key=config["incremental_key"],
                unique_key=tuple(config["unique_key"]),
                lookback_seconds=config.get("lookback_seconds", 0),
            ),
            column_types=column_types or None,
            database=database,
        )
        if not result.eligible:
            self._refused_incremental_keys = result.blocked_keys
            raise serializers.ValidationError({"incremental": result.blockers})
        return attrs

    def _pending_output_columns(self, query_changed: bool) -> list[tuple[str, str | None]] | None:
        """The saved query's output columns as (name, ClickHouse type), in output order, or None when
        they are unknown before inference runs. A query's output can repeat a name, so this is a list.

        The stored columns describe the stored query, so they say nothing about a query being
        replaced. For a new query, only the types the editor sends from running it are known here."""
        if not query_changed:
            assert self.instance is not None
            stored = self.instance.columns if isinstance(self.instance.columns, dict) else {}
            return [(name, meta.get("clickhouse") if isinstance(meta, dict) else None) for name, meta in stored.items()]
        client_types = self.context["request"].data.get("types")
        if (
            not isinstance(client_types, list)
            or not client_types
            or any(
                not isinstance(item, list | tuple)
                or len(item) != 2
                or not isinstance(item[0], str)
                or not isinstance(item[1], str)
                for item in client_types
            )
        ):
            return None
        return [(name, clickhouse_type) for name, clickhouse_type in client_types]

    def _changes_what_materializes(self, attrs: dict[str, Any], incremental: bool) -> bool:
        """Whether this write sets what a materialized table is built from: the query of a materialized
        view, or settings that make the view materialize. Pausing or renaming a view builds nothing."""
        if not {"query", "incremental_config", "sync_frequency"} & attrs.keys():
            return False
        if incremental or attrs.get("sync_frequency") not in (None, "never"):
            return True
        return "query" in attrs and self.instance is not None and bool(self.instance.is_materialized)

    def validate_is_test(self, is_test):
        if is_test and not self.context["request"].user.is_staff:
            raise serializers.ValidationError("Only staff users can create test views.")
        return is_test

    def validate_folder(self, folder):
        if folder is not None and folder.team_id != self.context["team_id"]:
            raise serializers.ValidationError("Folder not found.")
        return folder

    def validate_name(self, name):
        own_models_name: str | None = None
        # if it's an upsert, we don't want to validate the name
        if self.instance is not None and isinstance(self.instance, DataWarehouseSavedQuery):
            if self.instance.name == name:
                return name
            # The model's save() also rejects this name, but a Django ValidationError from save() becomes a 500.
            if is_reserved_models_name(name) and self.instance.origin in {
                DataWarehouseSavedQuery.Origin.ENDPOINT,
                DataWarehouseSavedQuery.Origin.MANAGED_VIEWSET,
            }:
                raise serializers.ValidationError(MODELS_NAMESPACE_QUERY_ERROR)
            own_chain = models_namespace_chain(self.instance)
            own_models_name = ".".join(own_chain) if own_chain is not None else None

        validate_saved_query_name(name)

        # An authored model answers to `models.<its name>` for the whole team, and has_table hides models the
        # caller is denied, so a denied caller could otherwise take that name over for everyone.
        instance = self.instance if isinstance(self.instance, DataWarehouseSavedQuery) else None
        owner = _authored_model_answering_to(self.context["team_id"], name, instance)
        if owner is not None:
            if self.context["database"].has_table(owner.name):
                raise serializers.ValidationError(
                    f"This name already refers to the model {owner.name}. Choose a different name."
                )
            raise serializers.ValidationError("A table or view with this name already exists. Choose a different name.")

        # has_table covers system/posthog tables and warehouse objects the requesting user can see; it's
        # user-filtered, so also resolve the name team-wide using get_view_or_table_by_name.
        # Otherwise a user with denied table could create another one with colliding name.
        # An authored model already resolves under `models.<stored name>`, so a rename to that name
        # collides with nothing. The two lookups below still reject it if a stored view or table holds it.
        if (
            (name != own_models_name and self.context["database"].has_table(name))
            or get_view_or_table_by_name(self.context["team_id"], name)
            or DataWarehouseSavedQuery.objects.filter(team_id=self.context["team_id"], name=name, deleted=True).exists()
        ):
            raise serializers.ValidationError("A table or view with this name already exists. Choose a different name.")

        return name
