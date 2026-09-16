"""Sync cadence for a saved query: the choices, the lineage bounds, and the writable field."""

from datetime import timedelta
from typing import Any, cast

from django.db import models
from django.db.models import Model

from rest_framework import serializers

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseTable,
    sync_frequency_interval_to_sync_frequency,
)

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


class SyncFrequencyBlockedBy(models.TextChoices):
    SOURCE = "source", "source"
    CONSUMER = "consumer", "consumer"


class SyncFrequencyOptionSerializer(serializers.Serializer):
    cadence = serializers.ChoiceField(choices=MATERIALIZE_SYNC_FREQUENCY_CHOICES, help_text="A `sync_frequency` value.")
    allowed = serializers.BooleanField(help_text="False when writing this cadence would be rejected.")
    blocked_by = serializers.ChoiceField(
        choices=SyncFrequencyBlockedBy.choices,
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
            ("managed_viewset", "managed_viewset"),
            ("legacy", "legacy"),
            ("no_node", "no_node"),
        ],
        help_text="What governs this view's cadence. 'tiered' is the only mode where `options` is "
        "meaningful and `sync_frequency` is writable per view. 'managed_viewset' means PostHog owns "
        "the view, 'legacy' means the v1 backend, where any cadence is accepted and no bounds apply, "
        "and 'no_node' means the view has no data modeling node to store a cadence on.",
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
