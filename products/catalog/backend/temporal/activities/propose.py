"""Propose deterministic relationships between catalog nodes.

Two activities, each walking a different source of declared edges. Both
write via `CatalogAPI.propose_relationship` with `confidence=1.0` — the
facade lands such edges as `status=ACCEPTED` on first insert (re-runs leave
status alone, preserving human review actions).

  - propose_warehouse_joins    DataWarehouseJoin rows seeded by source templates
                               (Stripe/Hubspot/etc.) + team-authored joins.
  - propose_saved_query_lineage `DataWarehouseSavedQuery.external_tables`
                               (pre-computed list of referenced tables).

Foreign-key edges between HogQL system tables used to be introspected from
Django models here. They are now declared inline on each `PostgresTable` in
`posthog/hogql/database/schema/system.py` via the `relationships=` argument
and exposed through `system.relationships` directly (no Postgres write).

Each activity returns the number of edges written. The workflow accumulates
these into `counts.relationships`.
"""

import re
import asyncio
from uuid import UUID

from temporalio import activity

from products.catalog.backend.facade.api import CatalogAPI
from products.catalog.backend.facade.contracts import ProposeRelationshipParams
from products.catalog.backend.models import CatalogColumn, CatalogNode, CatalogRelationship
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.join import DataWarehouseJoin

_SIMPLE_COLUMN_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# --- propose_warehouse_joins --------------------------------------------------


@activity.defn
async def propose_warehouse_joins(team_id: int) -> int:
    """Materialize `DataWarehouseJoin` rows as declared_join edges in the catalog."""
    return await asyncio.to_thread(_propose_warehouse_joins_sync, team_id)


def _propose_warehouse_joins_sync(team_id: int) -> int:
    count = 0
    for join in DataWarehouseJoin.objects.filter(team_id=team_id, deleted=False):
        source_node_id = _node_id_by_name(team_id, join.source_table_name)
        target_node_id = _node_id_by_name(team_id, join.joining_table_name)
        if source_node_id is None or target_node_id is None:
            # One side isn't in the catalog yet — possibly a saved query the
            # user has deleted or a table that hasn't been re-synced. Skip;
            # the next traversal pass will pick it up if it reappears.
            continue

        # Keys can be plain column names ("email") or HogQL expressions
        # ("properties.email"). For expressions, we leave the column refs null
        # and preserve the full expression in `reasoning`.
        source_column_id = (
            _column_id(source_node_id, join.source_table_key)
            if _SIMPLE_COLUMN_NAME.match(join.source_table_key)
            else None
        )
        target_column_id = (
            _column_id(target_node_id, join.joining_table_key)
            if _SIMPLE_COLUMN_NAME.match(join.joining_table_key)
            else None
        )

        CatalogAPI.propose_relationship(
            ProposeRelationshipParams(
                team_id=team_id,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                source_column_id=source_column_id,
                target_column_id=target_column_id,
                kind=CatalogRelationship.Kind.DECLARED_JOIN,
                confidence=1.0,
                reasoning=(
                    f"DataWarehouseJoin: {join.source_table_name}.{join.source_table_key} → "
                    f"{join.joining_table_name}.{join.joining_table_key}"
                ),
            )
        )
        count += 1

    return count


# --- propose_saved_query_lineage ---------------------------------------------


@activity.defn
async def propose_saved_query_lineage(team_id: int) -> int:
    """Walk every saved query's pre-computed `external_tables` list → lineage edges."""
    return await asyncio.to_thread(_propose_saved_query_lineage_sync, team_id)


def _propose_saved_query_lineage_sync(team_id: int) -> int:
    count = 0
    for sq in DataWarehouseSavedQuery.objects.filter(team_id=team_id, deleted=False):
        sq_node_id = _node_id(team_id, CatalogNode.Kind.SAVED_QUERY, sq.name)
        if sq_node_id is None:
            continue

        for referenced_name in sq.external_tables or []:
            target_node_id = _node_id_by_name(team_id, referenced_name)
            if target_node_id is None:
                continue

            CatalogAPI.propose_relationship(
                ProposeRelationshipParams(
                    team_id=team_id,
                    source_node_id=sq_node_id,
                    target_node_id=target_node_id,
                    kind=CatalogRelationship.Kind.LINEAGE,
                    confidence=1.0,
                    reasoning=f"Saved query references table: {sq.name} → {referenced_name}",
                )
            )
            count += 1

    return count


# --- helpers ------------------------------------------------------------------


def _node_id(team_id: int, kind: str, name: str) -> UUID | None:
    return CatalogNode.objects.filter(team_id=team_id, kind=kind, name=name).values_list("id", flat=True).first()


def _node_id_by_name(team_id: int, name: str) -> UUID | None:
    """Look up a catalog node by name across all kinds.

    Used when the caller (e.g. DataWarehouseJoin, saved-query lineage) doesn't
    carry kind info. Returns the first match; collisions across kinds are
    theoretically possible but rare in practice.
    """
    return CatalogNode.objects.filter(team_id=team_id, name=name).values_list("id", flat=True).first()


def _column_id(node_id: UUID, column_name: str) -> UUID | None:
    return CatalogColumn.objects.filter(node_id=node_id, name=column_name).values_list("id", flat=True).first()
