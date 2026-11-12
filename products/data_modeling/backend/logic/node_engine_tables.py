from django.db.models import QuerySet

from posthog.models import Team

from products.data_modeling.backend.facade.contracts import MaterializationEngine
from products.data_modeling.backend.models.node_engine_table import NodeEngineTable
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


def _team_engine_tables(team: Team) -> QuerySet[NodeEngineTable]:
    return NodeEngineTable.objects.for_team(team.parent_team_id or team.pk, canonical=True)


def engine_tables_by_saved_query_id(team: Team, engine: MaterializationEngine) -> dict[str, DataWarehouseTable]:
    """The live table `engine` wrote for each materialized saved query of the team, keyed by saved query id.

    A view that is no longer materialized has no entry: the copy is stale once materialization stops.
    """
    rows = (
        _team_engine_tables(team)
        .filter(engine=engine, node__team_id=team.pk, node__saved_query__is_materialized=True)
        .exclude(table__deleted=True)
        .select_related("table", "node")
        .order_by("updated_at")
    )
    return {str(row.node.saved_query_id): row.table for row in rows}


def engine_table_ids(team: Team) -> QuerySet[NodeEngineTable, str]:
    """The ids of every table any engine wrote for the team's nodes, as a subquery for the warehouse table list.

    These tables back views. They are not tables a team connected, so the catalog must not list them.
    """
    return _team_engine_tables(team).values_list("table_id", flat=True)
