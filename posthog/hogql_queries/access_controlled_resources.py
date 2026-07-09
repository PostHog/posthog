import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from typing import TYPE_CHECKING, Optional

from django.core.signals import request_finished, request_started
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from celery.signals import task_postrun, task_prerun
from pydantic import BaseModel

from posthog.schema import DataWarehouseNode, FunnelsDataWarehouseNode, LifecycleDataWarehouseNode

if TYPE_CHECKING:
    from posthog.models import Team

# Scoped memoization for `_warehouse_and_view_names`. The cache fingerprint runs before any
# cache lookup — on every run of every query, including cache hits — and a single request or
# task can fingerprint many HogQL queries (e.g. a dashboard with N SQL tiles), each of which
# would otherwise issue an identical catalog lookup. We cache the name sets keyed by team_id
# for the lifetime of a scope and discard the cache when the scope closes.
#
# The ContextVar defaults to ``None`` which means "no scope active — do not cache". This is
# critical: the catalog partitions the query cache key (a security boundary), so a
# thread-lifetime cache could fingerprint against a stale catalog after tables changed.
# Scopes are opened at HTTP request boundaries (`request_started` / `request_finished`) and
# Celery task boundaries (`task_prerun` / `task_postrun`); callers outside those boundaries
# (Temporal activities, management commands, scripts) simply pay the query cost.
_warehouse_names_cache_var: ContextVar[Optional[dict[int, tuple[set[str], set[str]]]]] = ContextVar(
    "queried_warehouse_names_cache", default=None
)


@contextlib.contextmanager
def warehouse_names_cache_scope() -> Iterator[None]:
    """Open a memoization scope for the warehouse catalog lookup backing
    `queried_access_controlled_resources`.

    Use this to bracket any non-HTTP, non-Celery code path that fingerprints several
    queries for the same team (e.g. scripts or tests that want the per-request behavior
    without going through the signal plumbing).
    """
    token = _warehouse_names_cache_var.set({})
    try:
        yield
    finally:
        _warehouse_names_cache_var.reset(token)


@receiver(request_started)
@receiver(task_prerun)
def _open_warehouse_names_cache_scope(**_kwargs: object) -> None:
    _warehouse_names_cache_var.set({})


@receiver(request_finished)
@receiver(task_postrun)
def _close_warehouse_names_cache_scope(**_kwargs: object) -> None:
    _warehouse_names_cache_var.set(None)


# Lazy string senders keep the warehouse models off this module's import path (it is imported
# by query_runner at module scope). Bulk writes (queryset.update / bulk_create) bypass these
# signals, but the flows that bulk-write catalog rows run in Temporal, where no scope is active.
@receiver(post_save, sender="warehouse_sources.DataWarehouseTable")
@receiver(post_delete, sender="warehouse_sources.DataWarehouseTable")
@receiver(post_save, sender="warehouse_sources.ExternalDataSource")
@receiver(post_delete, sender="warehouse_sources.ExternalDataSource")
@receiver(post_save, sender="data_modeling.DataWarehouseSavedQuery")
@receiver(post_delete, sender="data_modeling.DataWarehouseSavedQuery")
def _invalidate_warehouse_names_cache_on_change(**_kwargs: object) -> None:
    # The cached names derive from table and view rows plus each table's source (the prefixed
    # form), so any write to those invalidates the current scope's cache.
    cache = _warehouse_names_cache_var.get()
    if cache is not None:
        cache.clear()


def _warehouse_and_view_names(team: "Team") -> tuple[set[str], set[str]]:
    """All queryable warehouse table names and saved-query (view) names for the team,
    memoized per request/task scope keyed by team_id.

    External tables are queryable under BOTH their raw name and the prefixed
    source_type.prefix.table key (see database.py schema build), so both forms are included —
    otherwise a denied user could read an allowed user's cached rows via the raw name.
    """
    # Deferred to break the query_runner -> this module -> hogql import cycle.
    from posthog.hogql.database.database import get_data_warehouse_table_name  # noqa: PLC0415

    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery  # noqa: PLC0415
    from products.warehouse_sources.backend.facade.models import DataWarehouseTable  # noqa: PLC0415

    cache = _warehouse_names_cache_var.get()
    if cache is not None and (cached := cache.get(team.pk)) is not None:
        return cached

    warehouse_table_names: set[str] = set()
    tables = (
        DataWarehouseTable.objects.filter(team_id=team.pk)
        .exclude(deleted=True)
        .select_related("external_data_source")
        # Exactly the fields get_data_warehouse_table_name reads (pks are always fetched).
        # This runs on the hot path even on cache hits, so the wide `columns` schema JSON must
        # stay in Postgres; a field missing here would silently defer-load per row instead.
        .only(
            "name",
            "external_data_source__source_type",
            "external_data_source__prefix",
            "external_data_source__access_method",
        )
    )
    for table in tables:
        warehouse_table_names.add(table.name)
        warehouse_table_names.add(get_data_warehouse_table_name(table.external_data_source, table.name))

    view_names = set(
        DataWarehouseSavedQuery.objects.filter(team_id=team.pk).exclude(deleted=True).values_list("name", flat=True)
    )

    result = (warehouse_table_names, view_names)
    if cache is not None:
        cache[team.pk] = result
    return result


def queried_access_controlled_resources(query, team: "Team") -> Optional[set[str]]:
    """The set of access-control scope names a query reads, e.g. "notebook", "warehouse_table".
    Empty when the query reads no access-controlled table.
    None when the query is malformed or unparseable.

    This drives query-cache partitioning: a denied object the query reads must change the cache key,
    otherwise a denied user could be served an allowed user's cached rows on a cache hit (the hit
    short-circuits the schema strip that would otherwise raise "You don't have access to table")."""

    # Deferred to break the query_runner -> this module -> hogql import cycle.
    from posthog.hogql.database.schema.system import access_controlled_system_tables  # noqa: PLC0415
    from posthog.hogql.errors import BaseHogQLError  # noqa: PLC0415
    from posthog.hogql.metadata import get_table_names  # noqa: PLC0415
    from posthog.hogql.parser import parse_select  # noqa: PLC0415

    # Raw HogQL is the only query that references system.* and warehouse tables by name
    if getattr(query, "kind", None) == "HogQLQuery":
        sql = getattr(query, "query", None)
        if not isinstance(sql, str):
            return None
        try:
            select = parse_select(sql)
        except BaseHogQLError:
            return None  # unparseable -> fail closed

        table_names = set(get_table_names(select))
        system_scopes = {f"system.{name}": scope for name, scope in access_controlled_system_tables().items()}
        scopes: set[str] = {system_scopes[name] for name in table_names if name in system_scopes}

        # Warehouse tables/views are per-team and dynamic, and the HogQL schema isn't built here (the
        # fingerprint runs before any database), so resolve referenced warehouse objects with a light
        # name lookup. We only add the scope here; the specific denied object IDs are folded into the
        # cache key by AnalyticsQueryRunner._get_object_access_restrictions.
        non_system_names = table_names - set(system_scopes)
        if non_system_names:
            warehouse_table_names, view_names = _warehouse_and_view_names(team)
            if non_system_names & warehouse_table_names:
                scopes.add("warehouse_table")

            if non_system_names & view_names:
                scopes.add("warehouse_view")
                # A non-materialized view re-resolves to its underlying warehouse tables at execution.
                # A cache hit skips that resolution, so fold warehouse_table denials into the key too —
                # otherwise a user denied an underlying table could be served a cached view result.
                scopes.add("warehouse_table")

        return scopes

    # Structured insight queries (Trends/Funnels/Lifecycle/...) read warehouse data via a
    # DataWarehouseNode in their tree rather than by table name.
    return {"warehouse_table", "warehouse_view"} if _references_data_warehouse(query) else set()


def _references_data_warehouse(value) -> bool:
    """True if a structured query reads a data-warehouse source via a DataWarehouseNode anywhere in
    its tree (series, sub-queries, exclusions, ...)"""
    if isinstance(value, (DataWarehouseNode, FunnelsDataWarehouseNode, LifecycleDataWarehouseNode)):
        return True
    if isinstance(value, BaseModel):
        return any(_references_data_warehouse(field) for field in value.__dict__.values())
    if isinstance(value, (list, tuple)):
        return any(_references_data_warehouse(item) for item in value)
    if isinstance(value, dict):
        return any(_references_data_warehouse(item) for item in value.values())
    return False
