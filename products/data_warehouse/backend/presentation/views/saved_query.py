import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Model, OuterRef, Prefetch, Q, Subquery, TextField
from django.db.models.functions import Cast

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import exceptions, filters, request, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from posthog.schema import DataWarehouseManagedViewsetKind

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database, SerializedField, serialize_fields
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import FindPlaceholders
from posthog.hogql.printer import prepare_and_print_ast

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer
from posthog.exceptions_capture import capture_exception
from posthog.helpers.impersonation import is_impersonated
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import (
    ActivityLog,
    Change,
    Detail,
    changes_between,
    load_activity,
    log_activity,
)
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.rate_limit import MaterializationRateThrottle, PersonalApiKeyOrUserRateThrottle, RunSavedQueryRateThrottle
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.query_access import assert_user_can_read_query
from posthog.rbac.user_access_control import UserAccessControl, UserAccessControlSerializerMixin
from posthog.temporal.common.client import sync_connect

from products.data_modeling.backend.facade.api import MAX_LOOKBACK_SECONDS, get_incremental_config
from products.data_modeling.backend.facade.modeling import DataWarehouseModelPath
from products.data_modeling.backend.facade.models import (
    DataModelingJob,
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryColumnAnnotation,
)
from products.data_tools.backend.facade.models import DataWarehouseJoin, DataWarehouseSavedQueryFolder
from products.data_warehouse.backend.facade.api import (
    pause_saved_query_schedule,
    saved_query_workflow_exists,
    sync_saved_query_workflow,
    trigger_saved_query_schedule,
    unpause_saved_query_schedule,
)
from products.data_warehouse.backend.presentation.views.column_annotation_base import (
    DESCRIPTION_HELP_TEXT,
    upsert_annotation,
)
from products.warehouse_sources.backend.facade.hogql import (
    CLICKHOUSE_HOGQL_MAPPING,
    clean_type,
    get_view_or_table_by_name,
)
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseTable,
    sync_frequency_interval_to_sync_frequency,
    sync_frequency_to_sync_frequency_interval,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class _CancelTarget:
    workflow_id: str
    workflow_run_id: str | None


# A DataWarehouseSavedQuery's activity log also records materialization syncs and status
# transitions (activity="sync_triggered", status changes) that advance the log without the query
# being edited. Optimistic-concurrency ("modified by someone else") must key off the latest activity
# that actually changed the query — otherwise every background sync of a materialized view looks
# like a foreign edit and blocks the next save. This filter scopes activity lookups to query edits.
QUERY_CHANGE_ACTIVITY_FILTER = {"detail__changes__contains": [{"field": "query"}]}

# Cadences offered for view materialization. 15min is the fastest — sub-15min intervals
# (1min, 5min) are source-only and not meaningful for materialized views, matching the
# frontend `DataModelingSyncInterval` type. All values are accepted by
# `sync_frequency_to_sync_frequency_interval`.
SYNC_FREQUENCY_CHOICES = [
    ("never", "never"),
    ("15min", "15min"),
    ("30min", "30min"),
    ("1hour", "1hour"),
    ("6hour", "6hour"),
    ("12hour", "12hour"),
    ("24hour", "24hour"),
    ("7day", "7day"),
    ("30day", "30day"),
]

# Deprecated sub-15min cadences clamped up to the 15min floor for backwards compatibility
# with any legacy caller still sending them.
DEPRECATED_FAST_SYNC_FREQUENCIES = {"1min", "5min"}

# What `materialize` enables at when the caller expresses no preference, preserving the
# behavior from when the action had no request body at all.
DEFAULT_MATERIALIZE_SYNC_FREQUENCY = "24hour"

# `never` is missing on purpose: materializing is what starts the refreshes, so asking for none
# has no meaning here. Callers stop them afterwards by setting the cadence to `never`.
MATERIALIZE_SYNC_FREQUENCY_CHOICES = [choice for choice in SYNC_FREQUENCY_CHOICES if choice[0] != "never"]


SYNC_FREQUENCY_MANAGED_BY_DAG_HELP_TEXT = (
    "True when this team's DAG owns the materialization cadence through a single schedule, so "
    "`sync_frequency` cannot be set per view and writes to it are rejected. False when per-node DAG "
    "schedules are in use or the team is on the v1 backend. False does not on its own mean the "
    "cadence is writable: a view belonging to a managed viewset rejects every update regardless, "
    "which `managed_viewset_kind` reports."
)


class SyncFrequencyBlockerSerializer(serializers.Serializer):
    """The node holding a cadence back, named so a refusal points at something a person can open."""

    id = serializers.CharField(help_text="Data modeling node ID of the source or view.")
    name = serializers.CharField(help_text="Node name, as it appears in the data modeling graph.")


class SyncFrequencyBoundSerializer(serializers.Serializer):
    label = serializers.CharField(  # type: ignore[assignment]  # field name intentionally shadows Field.label
        help_text="The bounding cadence in plain English, for example '6 hours'. Matches the wording "
        "used in the error raised when an out-of-bounds cadence is written. Prose rather than a "
        "`sync_frequency` value because a source can deliver on a cadence no `sync_frequency` names."
    )
    blocker = SyncFrequencyBlockerSerializer(
        allow_null=True,
        help_text="Node that set this bound. Null when nothing identifiable set it, and also when it "
        "sits outside the caller's access grants: the bound still applies, it just goes unnamed.",
    )


class SyncFrequencyOptionSerializer(serializers.Serializer):
    cadence = serializers.ChoiceField(choices=MATERIALIZE_SYNC_FREQUENCY_CHOICES, help_text="A `sync_frequency` value.")
    allowed = serializers.BooleanField(help_text="False when writing this cadence would be rejected.")
    blocked_by = serializers.ChoiceField(
        choices=[("source", "source"), ("consumer", "consumer")],
        allow_null=True,
        help_text="Which side withholds this cadence: 'source' when no upstream source syncs that "
        "often, 'consumer' when a downstream view or endpoint refreshes more often than this. "
        "Null when the cadence is allowed.",
    )
    blocker = SyncFrequencyBlockerSerializer(
        allow_null=True,
        help_text="The source or consumer named in `blocked_by`. Null when allowed, and also when the "
        "blocker sits outside the caller's access grants, where `blocked_by` still gives the direction.",
    )


class SyncFrequencyBoundsSerializer(serializers.Serializer):
    frequency_mode = serializers.ChoiceField(
        choices=[
            ("tiered", "tiered"),
            ("dag_schedule", "dag_schedule"),
            ("managed_viewset", "managed_viewset"),
            ("legacy", "legacy"),
            ("no_node", "no_node"),
        ],
        help_text="What governs this view's cadence. 'tiered' is the only mode where `options` is "
        "meaningful and `sync_frequency` is writable per view. 'dag_schedule' means the team's single "
        "DAG schedule owns it, 'managed_viewset' means PostHog owns the view, 'legacy' means the v1 "
        "backend, where any cadence is accepted and no bounds apply, and 'no_node' means the view has "
        "no data modeling node to store a cadence on.",
    )
    options = SyncFrequencyOptionSerializer(
        many=True,
        help_text="Every cadence a picker may show, coarsest-last, each marked allowed or blocked with "
        "its cause. Empty outside 'tiered' mode.",
    )
    floor = SyncFrequencyBoundSerializer(
        allow_null=True,
        help_text="The fastest bound: no cadence finer than this is allowed, because the source named "
        "here does not sync more often. Null when no source withholds a cadence.",
    )
    ceiling = SyncFrequencyBoundSerializer(
        allow_null=True,
        help_text="The slowest bound: no cadence coarser than this is allowed, because the consumer "
        "named here refreshes that often. Null when no consumer withholds a cadence.",
    )
    best_effort_sources = SyncFrequencyBlockerSerializer(
        many=True,
        help_text="Upstream sources with no sync schedule, so the floor is a guess: these arrive when "
        "someone runs them, and refreshing more often than they really sync will serve stale data. "
        "Only sources the caller may read are listed.",
    )
    best_effort_sources_withheld = serializers.BooleanField(
        help_text="True when at least one such source sits outside the caller's access grants, so the "
        "list above is incomplete and the caveat still applies."
    )


SYNC_FREQUENCY_BOUNDS_HELP_TEXT = (
    "Which cadences this view can actually be set to, and what withholds the rest. Computed from the "
    "view's data modeling lineage: upstream source sync frequencies set a floor, downstream cadences "
    "set a ceiling. Read-only, and present on retrieve, create and update responses only."
)


def _unbounded_frequency_payload(mode: str) -> dict[str, Any]:
    """The payload for a view whose cadence no lineage governs, so there is nothing to withhold."""
    return {
        "frequency_mode": mode,
        "options": [],
        "floor": None,
        "ceiling": None,
        "best_effort_sources": [],
        "best_effort_sources_withheld": False,
    }


def _blocker_node_ids(resolved: Any) -> set[str]:
    """Every node the bounds would name, across the two bounds, the options and the best-effort list."""
    node_ids: set[str] = set(resolved.best_effort_source_ids)
    for bound in (resolved.bounds.floor, resolved.bounds.ceiling):
        if bound is not None and bound.blocker is not None:
            node_ids.add(bound.blocker)
    node_ids.update(option.blocker for option in resolved.bounds.options if option.blocker is not None)
    return node_ids


def visible_blocker_names(
    resolved: Any, user_access_control: UserAccessControl | None, *, team_id: int
) -> dict[str, str]:
    """The blocker names this caller may read, keyed by node id.

    Fails closed, and withholds the node id along with the name: an id on its own still answers
    "something upstream of this view exists", which is what the grant is there to withhold. A node
    with no resolvable resource (predating the origin stamp) is withheld for the same reason.
    """
    node_ids = _blocker_node_ids(resolved)
    if not node_ids or user_access_control is None:
        return {}

    visible: dict[str, str] = {}
    # Lists, not single ids: one saved query or table can hold a node in several DAGs, and a grant
    # covers the resource, so every node of it becomes visible together.
    node_ids_by_saved_query: dict[str, list[str]] = {}
    node_ids_by_table: dict[str, list[str]] = {}
    for node_id in node_ids:
        identity = resolved.identities.get(node_id)
        name = resolved.names.get(node_id)
        if identity is None or name is None:
            continue
        if identity.is_posthog_table:
            visible[node_id] = name  # events, persons and friends: readable by anyone on the project
        elif identity.saved_query_id is not None:
            node_ids_by_saved_query.setdefault(identity.saved_query_id, []).append(node_id)
        elif identity.warehouse_table_id is not None:
            node_ids_by_table.setdefault(identity.warehouse_table_id, []).append(node_id)

    def reveal(resource_node_ids: list[str]) -> None:
        visible.update({node_id: resolved.names[node_id] for node_id in resource_node_ids})

    if node_ids_by_saved_query:
        creators = DataWarehouseSavedQuery.objects.filter(id__in=node_ids_by_saved_query, team_id=team_id).values_list(
            "id", "created_by_id"
        )
        levels = user_access_control.bulk_object_access_levels(
            "warehouse_view", [(str(pk), created_by) for pk, created_by in creators]
        )
        for saved_query_id, level in levels.items():
            if level is not None and level != "none":
                reveal(node_ids_by_saved_query[saved_query_id])

    if node_ids_by_table:
        # One at a time rather than in bulk: `warehouse_table` falls back to `external_data_source`,
        # and the bulk call refuses any resource with a fallback parent. Per object is also what
        # honours a deny on one table, or on the source it came from. A table that no longer
        # resolves keeps its name withheld.
        tables = list(
            DataWarehouseTable.objects.filter(id__in=node_ids_by_table, team_id=team_id).exclude(deleted=True)
        )
        user_access_control.preload_object_access_controls(cast(list[Model], tables))
        for table in tables:
            if user_access_control.check_access_level_for_object(table, "viewer"):
                reveal(node_ids_by_table[str(table.id)])
    return visible


def _frequency_bounds_payload(resolved: Any, visible_names: dict[str, str]) -> dict[str, Any]:
    from products.data_modeling.backend.facade.api import humanize_cadence

    def blocker(node_id: str | None) -> dict[str, str] | None:
        if node_id is None or node_id not in visible_names:
            return None
        return {"id": node_id, "name": visible_names[node_id]}

    def bound(value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        return {"label": humanize_cadence(value.value), "blocker": blocker(value.blocker)}

    best_effort = sorted(resolved.best_effort_source_ids)
    return {
        "frequency_mode": "tiered",
        "options": [
            {
                "cadence": sync_frequency_interval_to_sync_frequency(option.value),
                "allowed": option.allowed,
                "blocked_by": option.blocked_by,
                "blocker": blocker(option.blocker),
            }
            for option in resolved.bounds.options
        ],
        "floor": bound(resolved.bounds.floor),
        "ceiling": bound(resolved.bounds.ceiling),
        "best_effort_sources": [blocker(node_id) for node_id in best_effort if node_id in visible_names],
        "best_effort_sources_withheld": any(node_id not in visible_names for node_id in best_effort),
    }


def _node_frequency_targets(root: serializers.BaseSerializer, view: DataWarehouseSavedQuery) -> dict[str, timedelta]:
    """Declared node targets for every view the root serializer renders, fetched once.

    Resolved from the root's instance rather than the viewset context, because the context is
    built without knowing which page of views is being serialized. Memoized on the root so a
    `list` response costs one query instead of one per view.
    """
    cached = getattr(root, "_node_frequency_targets_cache", None)
    if cached is not None:
        return cached

    from products.data_modeling.backend.facade.api import declared_targets_by_saved_query

    instance = root.instance
    if isinstance(instance, DataWarehouseSavedQuery):
        views = [instance]
    elif instance is None:
        views = [view]
    else:
        views = list(instance)

    targets = declared_targets_by_saved_query(view.team_id, [rendered.pk for rendered in views])
    root._node_frequency_targets_cache = targets  # type: ignore[attr-defined]
    return targets


def resolve_sync_frequency(root: serializers.BaseSerializer, view: DataWarehouseSavedQuery) -> str | None:
    """Cadence string for a view, preferring its DAG node's declared freshness target.

    On tiered v2 teams the node target is the only store of cadence — reconcile deliberately NULLs
    `sync_frequency_interval` so a stale v1 schedule can't be revived from it — so reading the
    column alone reports "never" for every scheduled view. The column still covers v1 and
    single-schedule v2 teams, which have no node target.
    """
    target = _node_frequency_targets(root, view).get(str(view.pk))
    if target is not None:
        return sync_frequency_interval_to_sync_frequency(target)
    return sync_frequency_interval_to_sync_frequency(view.sync_frequency_interval)


class SyncFrequencyField(serializers.ChoiceField):
    """Writable sync-cadence field for saved queries.

    Reads resolve the cadence via `resolve_sync_frequency` (node target first, then the model's
    `sync_frequency_interval`); writes are validated against the choices and consumed by the
    serializer's `update()`. Declaring it as a real (non read-only) field is what lets the
    cadence flow into the generated PATCH body and MCP tool schema.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("choices", SYNC_FREQUENCY_CHOICES)
        kwargs.setdefault("required", False)
        kwargs.setdefault("allow_null", True)
        super().__init__(**kwargs)

    def to_internal_value(self, data: Any) -> str:
        # Clamp deprecated sub-15min cadences up to the floor before validating against choices.
        if data in DEPRECATED_FAST_SYNC_FREQUENCIES:
            data = "15min"
        return super().to_internal_value(data)

    def get_attribute(self, instance: DataWarehouseSavedQuery) -> str | None:
        return resolve_sync_frequency(self.root, instance)


def delete_saved_query(saved_query: DataWarehouseSavedQuery) -> None:
    from products.data_modeling.backend.facade.api import HasDependentsError, delete_node_from_dag

    if saved_query.managed_viewset is not None:
        raise serializers.ValidationError(
            "Cannot delete a query from a managed viewset directly. Disable the managed viewset instead."
        )

    try:
        delete_node_from_dag(saved_query)
    except HasDependentsError:
        raise
    except Exception as e:
        capture_exception(e)
        logger.exception("Failed to delete node for saved query", saved_query_name=saved_query.name)

    for join in DataWarehouseJoin.objects.filter(
        Q(team_id=saved_query.team_id)
        & (Q(source_table_name=saved_query.name) | Q(joining_table_name=saved_query.name))
    ).exclude(deleted=True):
        join.soft_delete()

    saved_query.revert_materialization()
    saved_query.soft_delete()


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

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_last_run_at(self, view: DataWarehouseSavedQuery) -> datetime | None:
        try:
            jobs = view.jobs  # type: ignore
            if len(jobs) > 0:
                return jobs[0].last_run_at
        except Exception:
            pass

        return view.last_run_at

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_sync_frequency(self, schema: DataWarehouseSavedQuery):
        return resolve_sync_frequency(self.root, schema)  # type: ignore[attr-defined]

    @extend_schema_field(serializers.BooleanField())
    def get_is_incremental(self, view: DataWarehouseSavedQuery) -> bool:
        return get_incremental_config(view) is not None

    @extend_schema_field(serializers.BooleanField())
    def get_sync_frequency_managed_by_dag(self, view: DataWarehouseSavedQuery) -> bool:
        return bool(self.context.get("sync_frequency_managed_by_dag", False))  # type: ignore[attr-defined]

    @extend_schema_field(SyncFrequencyBoundsSerializer())
    def get_sync_frequency_bounds(self, view: DataWarehouseSavedQuery) -> dict[str, Any]:
        from products.data_modeling.backend.facade.api import saved_query_target_bounds

        team_mode = self.context.get("team_frequency_mode", "legacy")  # type: ignore[attr-defined]
        if view.managed_viewset is not None:
            return _unbounded_frequency_payload("managed_viewset")
        if team_mode != "tiered":
            return _unbounded_frequency_payload(team_mode)

        resolved = saved_query_target_bounds(view.team_id, view.pk)
        if resolved is None:
            return _unbounded_frequency_payload("no_node")
        visible = visible_blocker_names(resolved, self.user_access_control, team_id=view.team_id)  # type: ignore[attr-defined]
        return _frequency_bounds_payload(resolved, visible)

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
    sync_frequency_managed_by_dag = serializers.SerializerMethodField(
        read_only=True, help_text=SYNC_FREQUENCY_MANAGED_BY_DAG_HELP_TEXT
    )
    last_run_at = serializers.SerializerMethodField(read_only=True)
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
            "sync_frequency_managed_by_dag",
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
    sync_frequency = SyncFrequencyField(
        help_text=(
            "How often to materialize this view. One of '15min', '30min', '1hour', '6hour', '12hour', "
            "'24hour', '7day', '30day', or 'never' to pause scheduled materialization. 15min is the fastest "
            "cadence available. Null means no scheduled materialization. Read back after a write, this "
            "reflects the stored cadence wherever it lives. On teams whose DAG schedules are managed "
            "per-node, that is the view's DAG node rather than the view itself."
        ),
    )
    sync_frequency_managed_by_dag = serializers.SerializerMethodField(
        read_only=True, help_text=SYNC_FREQUENCY_MANAGED_BY_DAG_HELP_TEXT
    )
    sync_frequency_bounds = serializers.SerializerMethodField(read_only=True, help_text=SYNC_FREQUENCY_BOUNDS_HELP_TEXT)
    latest_history_id = serializers.SerializerMethodField(read_only=True)
    last_run_at = serializers.SerializerMethodField(read_only=True)
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
            "sync_frequency_managed_by_dag",
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
            "sync_frequency_managed_by_dag",
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
                            "hogql": CLICKHOUSE_HOGQL_MAPPING[clean_type(str(item[1]))].__name__,
                            "clickhouse": item[1],
                            "valid": True,
                        }
                        for item in client_types
                    }
                    view.set_columns(columns)

                view.external_tables = view.s3_tables
            except Exception as e:
                capture_exception(e)
                logger.exception("Failed to retrieve types for view %s", view.name)
                raise serializers.ValidationError("Failed to retrieve types for view")

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

        dag_managed_frequency = False
        if sync_frequency and posthoganalytics.feature_enabled(
            "data-modeling-backend-v2",
            str(instance.team.uuid),
            groups={
                "organization": str(instance.team.organization_id),
                "project": str(instance.team.id),
            },
        ):
            from products.data_modeling.backend.facade.api import tiered_schedules_enabled

            # On tiered v2 the frequency writes through to the DAG node's freshness target;
            # on single-schedule v2 the DAG's one schedule owns cadence and per-query
            # frequency edits are rejected.
            if not tiered_schedules_enabled(instance.team):
                raise serializers.ValidationError("Schedule is managed by the DAG. Edit the DAG schedule instead.")
            dag_managed_frequency = True

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

            if dag_managed_frequency:
                # Tiered v2: the node target is the only store of frequency intent. The
                # interval column stays NULL so a stale v1 schedule can never be revived
                # from it.
                locked_instance.sync_frequency_interval = None
                validated_data["sync_frequency_interval"] = None
            elif sync_frequency == "never":
                locked_instance.sync_frequency_interval = None
                validated_data["sync_frequency_interval"] = None
            elif sync_frequency:
                sync_frequency_interval = sync_frequency_to_sync_frequency_interval(sync_frequency)
                validated_data["sync_frequency_interval"] = sync_frequency_interval
                locked_instance.sync_frequency_interval = sync_frequency_interval

            view: DataWarehouseSavedQuery = super().update(locked_instance, validated_data)

            if dag_managed_frequency:
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
                    visible_blocker_names(bounds, self.user_access_control, team_id=view.team_id)
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
                                "hogql": CLICKHOUSE_HOGQL_MAPPING[clean_type(str(item[1]))].__name__,
                                "clickhouse": item[1],
                                "valid": True,
                            }
                            for item in client_types
                        }
                        view.set_columns(columns)

                    view.external_tables = view.s3_tables
                except RecursionError:
                    raise serializers.ValidationError("Model contains a cycle")
                except Exception as e:
                    capture_exception(e)
                    logger.exception("Failed to retrieve types for view %s", view.name)
                    raise serializers.ValidationError("Failed to retrieve types for view")

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
            if dag_managed_frequency and previous_target != target:
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
            # Update the v1 temporal schedule if it exists. Skipped on the DAG-managed path even
            # when a stale v1 schedule lingers from a half-finished migration — syncing it here
            # would revive it alongside the DAG's schedules.
            if not dag_managed_frequency:
                temporal_schedule_exists = saved_query_workflow_exists(view)
                if temporal_schedule_exists:
                    try:
                        if sync_frequency == "never":
                            pause_saved_query_schedule(view)
                        elif sync_frequency:
                            sync_saved_query_workflow(view, create=not temporal_schedule_exists)
                    except Exception as e:
                        capture_exception(e)
                        logger.exception(
                            "Failed to update temporal schedule when updating view: view=%s sync_frequency=%s",
                            view.name,
                            sync_frequency,
                        )
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


class DataWarehouseSavedQueryFolderSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    view_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = DataWarehouseSavedQueryFolder
        fields = ["id", "name", "created_at", "created_by", "view_count", "user_access_level"]
        read_only_fields = ["id", "created_at", "created_by", "view_count", "user_access_level"]
        extra_kwargs = {
            "name": {
                "help_text": "Display name for the folder used to organize saved queries in the SQL editor sidebar."
            }
        }

    def validate_name(self, name: str) -> str:
        normalized_name = name.strip()
        if not normalized_name:
            raise serializers.ValidationError("Folder name cannot be empty.")

        team_id = self.context["team_id"]
        queryset = DataWarehouseSavedQueryFolder.objects.filter(team_id=team_id, name=normalized_name)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError("A folder with this name already exists.")

        return normalized_name


class DataWarehouseSavedQueryFolderViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    scope_object = "warehouse_view"
    queryset = DataWarehouseSavedQueryFolder.objects.all()
    serializer_class = DataWarehouseSavedQueryFolderSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete"]
    ordering = "name"

    def safely_get_queryset(self, queryset):
        return (
            queryset.filter(team_id=self.team_id)
            .select_related("created_by")
            .annotate(view_count=Count("saved_queries", filter=Q(saved_queries__deleted=False)))
            .order_by(self.ordering)
        )

    def perform_create(self, serializer):
        serializer.save(team_id=self.team_id, created_by=self.request.user)

    def destroy(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        from products.data_modeling.backend.facade.api import HasDependentsError

        folder: DataWarehouseSavedQueryFolder = self.get_object()
        remaining_queries = {
            saved_query.id: saved_query
            for saved_query in folder.saved_queries.filter(deleted=False).select_related("managed_viewset", "folder")
        }

        while remaining_queries:
            deleted_ids: list[uuid.UUID] = []

            for saved_query_id, saved_query in remaining_queries.items():
                try:
                    delete_saved_query(saved_query)
                    deleted_ids.append(saved_query_id)
                except HasDependentsError:
                    continue

            if not deleted_ids:
                blocked_names = ", ".join(sorted(saved_query.name for saved_query in remaining_queries.values()))
                raise serializers.ValidationError(
                    f"Cannot delete this folder because these views still have dependencies outside the folder: {blocked_names}"
                )

            for saved_query_id in deleted_ids:
                remaining_queries.pop(saved_query_id, None)

        folder.delete()
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class SavedQueryResumeSerializer(serializers.Serializer):
    resumed = serializers.BooleanField(help_text="False when the query's materialization was not suspended.")


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

    sync_frequency = SyncFrequencyField(
        choices=MATERIALIZE_SYNC_FREQUENCY_CHOICES,
        allow_null=False,
        default=DEFAULT_MATERIALIZE_SYNC_FREQUENCY,
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
    serializer_class = DataWarehouseSavedQuerySerializer
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
        context["team_frequency_mode"] = self._team_frequency_mode()
        context["sync_frequency_managed_by_dag"] = context["team_frequency_mode"] == "dag_schedule"
        return context

    def _team_frequency_mode(self) -> str:
        """Which backend owns materialization cadence for this team.

        Mirrors the branch `update()` takes on a `sync_frequency` write: `legacy` writes the interval
        column, `tiered` writes the DAG node's freshness target and is the only mode with bounds, and
        `dag_schedule` rejects the write because the team's one DAG schedule owns cadence. Team-scoped,
        so the per-view rejections (managed viewsets, views with no node) are not reflected here.
        """
        from products.data_modeling.backend.facade.api import tiered_schedules_enabled

        v2_enabled = posthoganalytics.feature_enabled(
            "data-modeling-backend-v2",
            str(self.team.uuid),
            groups={"organization": str(self.team.organization_id), "project": str(self.team.id)},
            send_feature_flag_events=False,
        )
        if not v2_enabled:
            return "legacy"
        return "tiered" if tiered_schedules_enabled(self.team) else "dag_schedule"

    def get_serializer_class(self):
        if self.action == "list":
            return DataWarehouseSavedQueryMinimalSerializer
        return DataWarehouseSavedQuerySerializer

    def safely_get_queryset(self, queryset):
        base_queryset = (
            queryset.prefetch_related(
                "created_by",
                "managed_viewset",
                "column_annotations",
                Prefetch(
                    "datamodelingjob_set", queryset=DataModelingJob.objects.order_by("-last_run_at")[:1], to_attr="jobs"
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
                    **QUERY_CHANGE_ACTIVITY_FILTER,
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
            delete_saved_query(instance)
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
            clear_incremental_state,
            is_saved_query_on_v2_schedule,
            materialize_saved_query,
        )

        body = SavedQueryRunSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        saved_query = self.get_object()

        if body.validated_data["full_refresh"]:
            # Dropping the watermark is the whole mechanism: the next run finds no progress to
            # build on and rebuilds. Done before dispatch so the run it triggers is the rebuild.
            clear_incremental_state(saved_query)

        if is_saved_query_on_v2_schedule(saved_query):
            materialize_saved_query(saved_query)
        else:
            trigger_saved_query_schedule(saved_query)

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

    @extend_schema(request=CheckIncrementalSerializer, responses={200: IncrementalEligibilitySerializer})
    @action(
        methods=["POST"],
        detail=False,
        required_scopes=["warehouse_view:read"],
        throttle_classes=[CheckIncrementalThrottle],
    )
    def check_incremental(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Report whether a query can be materialized incrementally, without running it.

        Parses the SQL only, so it is cheap enough to call from the editor as the user types. Lets
        the editor explain why the incremental option is unavailable before anything is saved.
        """
        from products.data_modeling.backend.facade.api import IncrementalConfig, check_incremental_eligibility

        body = CheckIncrementalSerializer(data=request.data)
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
            IncrementalEligibilitySerializer(
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
        from products.data_modeling.backend.facade.api import resume_saved_query

        resumed = resume_saved_query(self.get_object())

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

        if sync_frequency_interval is not None and self._team_frequency_mode() == "tiered":
            # Ask before writing, so the ordinary refusal never has to be undone below. Names only
            # what this caller may read, matching the bounds payload — otherwise one rejected
            # materialize reads back a node they were never shown.
            bounds = saved_query_target_bounds(self.team_id, saved_query.pk)
            try:
                check_saved_query_frequency_target(
                    saved_query,
                    sync_frequency_interval,
                    visible_names=(
                        visible_blocker_names(bounds, self.user_access_control, team_id=self.team_id) if bounds else {}
                    ),
                )
            except (UnsatisfiableFrequencyError, UnsupportedFrequencyTargetError) as e:
                raise serializers.ValidationError(str(e))

        should_unpause = saved_query.sync_frequency_interval is None
        previous_interval = saved_query.sync_frequency_interval
        previously_materialized = saved_query.is_materialized

        saved_query.sync_frequency_interval = sync_frequency_interval
        saved_query.is_materialized = True
        saved_query.save(update_fields=["sync_frequency_interval", "is_materialized"])

        # Enable materialization - this handles model path setup and schedule creation
        # If this fails, it will set is_materialized = False
        try:
            saved_query.schedule_materialization(unpause=should_unpause, trigger_immediate_run=True)
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

    @action(methods=["POST"], detail=False)
    def resume_schedules(self, request: request.Request, *args, **kwargs) -> response.Response:
        """
        Resume paused materialization schedules for multiple matviews.

        Accepts a list of view IDs in the request body: {"view_ids": ["id1", "id2", ...]}
        This endpoint is idempotent - calling it on already running or non-existent schedules is safe.
        """
        view_ids = request.data.get("view_ids", [])
        if not view_ids:
            return response.Response({"error": "view_ids is required"}, status=status.HTTP_400_BAD_REQUEST)
        saved_queries = DataWarehouseSavedQuery.objects.filter(id__in=view_ids, team_id=self.team_id)
        for saved_query in saved_queries:
            if saved_query_workflow_exists(saved_query):
                unpause_saved_query_schedule(saved_query)
        return response.Response(status=status.HTTP_202_ACCEPTED)

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

    @action(methods=["GET"], detail=True)
    def dependencies(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Return the count of immediate upstream and downstream dependencies for this saved query."""
        saved_query = self.get_object()
        saved_query_id = saved_query.id.hex

        # Count immediate upstream (parents) - get unique parents from all paths to this node
        upstream_paths = DataWarehouseModelPath.objects.filter(
            team=saved_query.team, path__lquery=f"*.{saved_query_id}"
        )
        upstream_ids: set[str] = set()
        for path in upstream_paths:
            if len(path.path) >= 2:
                # Get the immediate parent (second to last in path)
                parent_id = path.path[-2]
                upstream_ids.add(parent_id)

        # Count immediate downstream (children) - get unique children that reference this node
        downstream_paths = DataWarehouseModelPath.objects.filter(
            team=saved_query.team, path__lquery=f"*.{saved_query_id}.*"
        )
        downstream_ids: set[str] = set()
        for path in downstream_paths:
            # Find position of current view in path
            try:
                idx = path.path.index(saved_query_id)
                if idx + 1 < len(path.path):
                    # Get immediate child (next node after current)
                    child_id = path.path[idx + 1]
                    downstream_ids.add(child_id)
            except ValueError:
                continue

        return response.Response({"upstream_count": len(upstream_ids), "downstream_count": len(downstream_ids)})

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


def try_convert_to_uuid(s: str) -> uuid.UUID | str:
    try:
        return str(uuid.UUID(s))
    except ValueError:
        return s
