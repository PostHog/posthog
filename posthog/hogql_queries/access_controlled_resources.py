from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel

from posthog.schema import DataWarehouseNode, FunnelsDataWarehouseNode, LifecycleDataWarehouseNode

if TYPE_CHECKING:
    from posthog.models import Team


def queried_access_controlled_resources(query, team: "Team") -> Optional[set[str]]:
    """The set of access-control scope names a query reads, e.g. "notebook", "warehouse_table".
    Empty when the query reads no access-controlled table.
    None when the query is malformed or unparseable.

    This drives query-cache partitioning: a denied object the query reads must change the cache key,
    otherwise a denied user could be served an allowed user's cached rows on a cache hit (the hit
    short-circuits the schema strip that would otherwise raise "You don't have access to table")."""

    # Deferred to break the query_runner -> this module -> hogql import cycle.
    from posthog.hogql.database.database import get_data_warehouse_table_name  # noqa: PLC0415
    from posthog.hogql.database.schema.system import access_controlled_system_tables  # noqa: PLC0415
    from posthog.hogql.errors import BaseHogQLError  # noqa: PLC0415
    from posthog.hogql.metadata import get_table_names  # noqa: PLC0415
    from posthog.hogql.parser import parse_select  # noqa: PLC0415

    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery  # noqa: PLC0415
    from products.warehouse_sources.backend.models.table import DataWarehouseTable  # noqa: PLC0415

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
            warehouse_table_names = {
                get_data_warehouse_table_name(table.external_data_source, table.name)
                for table in DataWarehouseTable.objects.filter(team_id=team.pk)
                .exclude(deleted=True)
                .select_related("external_data_source")
            }
            if non_system_names & warehouse_table_names:
                scopes.add("warehouse_table")

            view_names = set(
                DataWarehouseSavedQuery.objects.filter(team_id=team.pk)
                .exclude(deleted=True)
                .values_list("name", flat=True)
            )
            if non_system_names & view_names:
                scopes.add("warehouse_view")

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
