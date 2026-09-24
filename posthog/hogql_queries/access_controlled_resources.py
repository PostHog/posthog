from dataclasses import field
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel

from posthog.schema import (
    DataWarehouseNode,
    EntityType,
    FunnelsDataWarehouseNode,
    HogQLQuery,
    LifecycleDataWarehouseNode,
    RetentionEntity,
)

from posthog.dataclasses import frozen

from products.access_control.backend.facade.user_access_control import RESOURCE_FALLBACK_MAP

if TYPE_CHECKING:
    from posthog.models import Team


# `system.information_schema` tables whose rows/columns are gated behind `data_catalog` read access
# (see `_can_read_catalog` in information_schema.py): `tables` carries the certification mark,
# `relationships` carries proposal confidence/reasoning, `metrics` is entirely catalog-governed, and
# `certifications` / `relationship_proposals` are the fully catalog-governed review queues. A query
# touching any of these must partition the cache by `data_catalog` access, or an allowed user's cached
# rows would be served to a denied user on a cache hit.
_DATA_CATALOG_INFORMATION_SCHEMA_TABLES = frozenset(
    {
        "system.information_schema.tables",
        "system.information_schema.relationships",
        "system.information_schema.metrics",
        "system.information_schema.certifications",
        "system.information_schema.relationship_proposals",
    }
)

# `system.information_schema` tables gated behind warehouse read access (see
# `_can_read_data_quality` in information_schema.py). They carry check definitions, run outcomes, and
# per-subject health. A query touching any of these must partition the cache by warehouse access,
# or an allowed user's cached rows would be served to a denied user on a cache hit.
_DATA_QUALITY_INFORMATION_SCHEMA_TABLES = frozenset(
    {
        "system.information_schema.data_quality_checks",
        "system.information_schema.data_quality_check_runs",
        "system.information_schema.data_quality_health",
    }
)

_ACCOUNT_COMMUNICATION_LAZY_FIELDS = frozenset({"email_threads", "support_tickets"})

# Scopes a system table's rows depend on beyond its own `access_scope`, because its visibility rules
# read another access-controlled table, or because it declares no scope of its own.
# `system.activity_logs` limits Canvas rows to the canvases in `system.canvases` (see
# activity_log_visibility.py), so its rows follow the caller's Canvas grants: without partitioning
# on `canvas` too, two users with identical activity-log access but different Canvas grants share
# one cache key, and the narrower one is served the wider one's Canvas rows.
_TRANSITIVE_SYSTEM_TABLE_SCOPES: dict[str, frozenset[str]] = {
    "system.activity_logs": frozenset({"canvas"}),
    # These predicates resolve scoped parents at execution, after a cache hit would return.
    # Keep row filtering on the parent so its creator exemption also applies to junction rows.
    "system._account_tagged_items": frozenset({"account"}),
    "system._account_resource_notebooks": frozenset({"account"}),
    "system._ticket_tagged_items": frozenset({"ticket"}),
    "system._ticket_assignments": frozenset({"ticket"}),
    "system._ticket_assignee_roles": frozenset({"ticket"}),
    # Task predicates need these public channel IDs even under object-only task grants.
    "system._task_public_channels": frozenset({"task"}),
    "system.customer_tasks": frozenset({"account"}),
}


@frozen(frozen=False)
class _WarehouseCatalog:
    """Warehouse reads shared by one fingerprint and every view definition it walks.

    Without it each nested view re-reads the team's whole table catalog, and a view that several
    other views read is walked once per path to it, so a dashboard over layered views spends
    minutes here before it can read a single cached result."""

    team_id: int
    table_names: Optional[set[str]] = None
    view_queries: dict[str, Any] = field(default_factory=dict)
    looked_up_names: set[str] = field(default_factory=set)
    walked_views: set[str] = field(default_factory=set)

    def get_table_names(self) -> set[str]:
        # Deferred to break the query_runner -> this module -> hogql import cycle.
        from posthog.hogql.database.database import get_data_warehouse_table_name  # noqa: PLC0415

        from products.warehouse_sources.backend.facade.models import DataWarehouseTable  # noqa: PLC0415

        if self.table_names is None:
            # External tables are queryable under BOTH their raw name and the prefixed
            # source_type.prefix.table key (see database.py schema build), so match either form —
            # otherwise a denied user could read an allowed user's cached rows via the raw name.
            self.table_names = set()
            for table in (
                DataWarehouseTable.objects.filter(team_id=self.team_id)
                .exclude(deleted=True)
                # clear the manager's created_by/schema eager-loads: select_related chains additively,
                # so without this the .only() below raises FieldError (created_by deferred + traversed)
                .select_related(None)
                .prefetch_related(None)
                .select_related("external_data_source")
                .only(
                    "name",
                    "external_data_source__source_type",
                    "external_data_source__prefix",
                    "external_data_source__access_method",
                )
            ):
                self.table_names.add(table.name)
                self.table_names.add(get_data_warehouse_table_name(table.external_data_source, table.name))
        return self.table_names

    def get_views(self, names: set[str]) -> list[tuple[str, Any]]:
        from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery  # noqa: PLC0415

        unknown_names = names - self.looked_up_names
        if unknown_names:
            self.view_queries.update(
                DataWarehouseSavedQuery.objects.filter(team_id=self.team_id, name__in=unknown_names)
                .exclude(deleted=True)
                .values_list("name", "query")
            )
            self.looked_up_names |= unknown_names
        return [(name, self.view_queries[name]) for name in sorted(names) if name in self.view_queries]


def queried_access_controlled_resources(
    query, team: "Team", *, bypassed_scopes: frozenset[str] = frozenset(), _catalog: Optional[_WarehouseCatalog] = None
) -> Optional[set[str]]:
    """The set of access-control scope names a query reads, e.g. "notebook", "warehouse_table".
    Empty when the query reads no access-controlled table.
    None when the query is malformed or unparseable.

    This drives query-cache partitioning: a denied object the query reads must change the cache key,
    otherwise a denied user could be served an allowed user's cached rows on a cache hit (the hit
    short-circuits the schema strip that would otherwise raise "You don't have access to table").

    `bypassed_scopes` are the scopes whose access control the principal bypasses. The parent such a
    scope falls back to through `RESOURCE_FALLBACK_MAP` is left out, because the principal never
    reaches the parent's rules; the parent still partitions the cache when a table carries that
    scope directly.

    `_catalog` carries the warehouse reads and the saved views already walked into nested calls. Each
    view is walked once per fingerprint: its scopes join the top-level result the first time, so a
    later path to it adds nothing, and views that reference each other end."""

    # Deferred to break the query_runner -> this module -> hogql import cycle.
    from posthog.hogql.database.schema.system import access_controlled_system_tables  # noqa: PLC0415
    from posthog.hogql.errors import BaseHogQLError  # noqa: PLC0415
    from posthog.hogql.metadata import get_table_names  # noqa: PLC0415
    from posthog.hogql.parser import parse_expr, parse_select  # noqa: PLC0415
    from posthog.hogql.visitor import GetFieldsTraverser  # noqa: PLC0415

    catalog = _catalog or _WarehouseCatalog(team_id=team.pk)

    if getattr(query, "kind", None) == "AccountsTableQuery":
        return _with_fallback_parents({"account"}, bypassed_scopes)

    if getattr(query, "kind", None) == "AccountsQuery":
        expressions = [
            *(getattr(query, "select", None) or []),
            *(getattr(query, "metrics", None) or []),
            *(getattr(query, "orderBy", None) or []),
        ]
        filter_expression = getattr(query, "filterExpression", None)
        if filter_expression:
            expressions.append(filter_expression)
        try:
            fields = [
                field for expression in expressions for field in GetFieldsTraverser(parse_expr(expression)).fields
            ]
        except BaseHogQLError:
            return None
        account_scopes = {"account"}
        if any(any(str(segment) in _ACCOUNT_COMMUNICATION_LAZY_FIELDS for segment in field.chain) for field in fields):
            account_scopes.add("ticket")
        return _with_fallback_parents(account_scopes, bypassed_scopes)

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

        # Cache partitioning runs before lazy joins resolve, so their resource scopes do not appear as table names yet.
        if "system.accounts" in table_names and any(
            any(str(segment) in _ACCOUNT_COMMUNICATION_LAZY_FIELDS for segment in field.chain)
            for field in GetFieldsTraverser(select).fields
        ):
            scopes.add("ticket")

        for name in table_names:
            scopes |= _TRANSITIVE_SYSTEM_TABLE_SCOPES.get(name, frozenset())

        # The catalog-enriched information_schema tables aren't PostgresTables, so they're absent from
        # `access_controlled_system_tables()`; gate them explicitly on `data_catalog` read access.
        if table_names & _DATA_CATALOG_INFORMATION_SCHEMA_TABLES:
            scopes.add("data_catalog")
            # Their row visibility also depends on per-object warehouse denials (`_catalog_table_visible`
            # and referenced-table filtering hide rows for sources/views the caller can't see), so
            # partition on warehouse access too. Without this, two `data_catalog` users with different
            # source grants share a cache key and the denied one is served the allowed one's certification
            # notes / proposal evidence on a hit. The specific denied object IDs fold into the key via
            # AnalyticsQueryRunner._get_object_access_restrictions.
            scopes.add("warehouse_table")
            scopes.add("warehouse_view")

        # The data-quality information_schema tables are gated on warehouse read access, and their
        # rows are hidden per the caller's warehouse-object denials (the loaders drop a
        # check/run/health row whose subject table or view the caller can't see). Without this, two
        # users with different warehouse grants share a cache key and the denied one is served the
        # allowed one's check configs and run counts on a hit. The specific denied object IDs fold
        # into the key via AnalyticsQueryRunner._get_object_access_restrictions.
        if table_names & _DATA_QUALITY_INFORMATION_SCHEMA_TABLES:
            scopes.add("data_catalog")
            scopes.add("warehouse_table")
            scopes.add("warehouse_view")

        # Connection-scoped queries read the external source's upstream data directly. Their tables
        # are virtual (named by ExternalDataSchema.name) or physical direct rows, which the
        # warehouse-table name lookup below can't reliably match — so fail closed and partition the
        # cache by both gates execution enforces: source viewer access (the connection resolver) and
        # backing warehouse-table access (the virtual-table build). Without this, a denied user
        # could be served an allowed user's cached upstream rows on a cache hit.
        if getattr(query, "connectionId", None):
            scopes.add("external_data_source")
            scopes.add("warehouse_table")

        # Warehouse tables/views are per-team and dynamic, and the HogQL schema isn't built here (the
        # fingerprint runs before any database), so resolve referenced warehouse objects with a light
        # name lookup. We only add the scope here; the specific denied object IDs are folded into the
        # cache key by AnalyticsQueryRunner._get_object_access_restrictions.
        non_system_names = table_names - set(system_scopes)
        if non_system_names:
            if non_system_names & catalog.get_table_names():
                scopes.add("warehouse_table")

            views = catalog.get_views(non_system_names)
            if views:
                scopes.add("warehouse_view")
                # A non-materialized view re-resolves to its underlying warehouse tables at execution.
                # A cache hit skips that resolution, so fold warehouse_table denials into the key too —
                # otherwise a user denied an underlying table could be served a cached view result.
                scopes.add("warehouse_table")
            # A cache hit also skips the access check on the system tables a definition reads. Materialized
            # views are walked too, since they expand to their definition unless the query reads materialized views.
            for view_name, view_query in views:
                if view_name in catalog.walked_views:
                    continue
                catalog.walked_views.add(view_name)
                view_sql = view_query.get("query") if isinstance(view_query, dict) else None
                if not isinstance(view_sql, str):
                    return None  # a view without a definition cannot expand -> fail closed
                nested = queried_access_controlled_resources(
                    HogQLQuery(query=view_sql),
                    team,
                    bypassed_scopes=bypassed_scopes,
                    _catalog=catalog,
                )
                if nested is None:
                    return None
                scopes |= nested

        return _with_fallback_parents(scopes, bypassed_scopes)

    # Structured insight queries (Trends/Funnels/Lifecycle/...) read warehouse data via a
    # DataWarehouseNode in their tree rather than by table name.
    return (
        _with_fallback_parents({"warehouse_table", "warehouse_view"}, bypassed_scopes)
        if _references_data_warehouse(query)
        else set()
    )


def _with_fallback_parents(scopes: set[str], bypassed_scopes: frozenset[str]) -> set[str]:
    """Add the parent of every scope that resolves through one, since the parent's rules decide the
    child's access. A bypassed child's parent is not added: the principal never reaches its rules.

    Only RESOURCE_FALLBACK_MAP. RESOURCE_INHERITANCE_MAP substitutes the parent's access for the
    child's rather than adding rules of its own, so there is nothing extra to partition on.
    """
    return scopes | {
        parent for child, parent in RESOURCE_FALLBACK_MAP.items() if child in scopes and child not in bypassed_scopes
    }


def _references_data_warehouse(value) -> bool:
    """True if a structured query reads a data-warehouse source via a DataWarehouseNode — or a
    data-warehouse RetentionEntity — anywhere in its tree (series, sub-queries, exclusions, ...)"""
    if isinstance(value, (DataWarehouseNode, FunnelsDataWarehouseNode, LifecycleDataWarehouseNode)):
        return True
    if isinstance(value, RetentionEntity) and value.type == EntityType.DATA_WAREHOUSE:
        return True
    if isinstance(value, BaseModel):
        return any(_references_data_warehouse(field) for field in value.__dict__.values())
    if isinstance(value, (list, tuple)):
        return any(_references_data_warehouse(item) for item in value)
    if isinstance(value, dict):
        return any(_references_data_warehouse(item) for item in value.values())
    return False
