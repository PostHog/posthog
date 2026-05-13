"""Propose deterministic relationships between catalog nodes.

Three activities, each walking a different source of declared edges. All
write via `CatalogAPI.propose_relationship` with `confidence=1.0` — the
facade lands such edges as `status=ACCEPTED` on first insert (re-runs leave
status alone, preserving human review actions).

  - propose_native_fks         Django ForeignKey introspection on system_table-kind
                               models. Most teams: ~50–150 edges.
  - propose_warehouse_joins    DataWarehouseJoin rows seeded by source templates
                               (Stripe/Hubspot/etc.) + team-authored joins.
  - propose_saved_query_lineage `DataWarehouseSavedQuery.external_tables`
                               (pre-computed list of referenced tables).

Each activity returns the number of edges written. The workflow accumulates
these into `counts.relationships`.
"""

import re
import asyncio
from uuid import UUID

from django.apps import apps
from django.db import models

from temporalio import activity

from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.database.schema.system import SystemTables

from products.catalog.backend.facade.api import CatalogAPI
from products.catalog.backend.facade.contracts import ProposeRelationshipParams
from products.catalog.backend.models import CatalogColumn, CatalogNode, CatalogRelationship
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.join import DataWarehouseJoin

# Targets we skip during FK introspection. The User FK is on nearly every
# model (created_by, modified_by) — declaring all of them would explode the
# graph without adding analytical value.
_FK_TARGET_SKIPLIST: set[str] = {"User"}

_SIMPLE_COLUMN_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# --- propose_native_fks -------------------------------------------------------


@activity.defn
async def propose_native_fks(team_id: int) -> int:
    """Walk SystemTables → Django model → ForeignKey fields → propose edges."""
    return await asyncio.to_thread(_propose_native_fks_sync, team_id)


def _propose_native_fks_sync(team_id: int) -> int:
    model_to_node_name = _build_model_to_node_name()

    count = 0
    for source_model, source_node_name in model_to_node_name.items():
        source_node_id = _node_id(team_id, CatalogNode.Kind.SYSTEM_TABLE, source_node_name)
        if source_node_id is None:
            continue

        for field in source_model._meta.get_fields():
            if not isinstance(field, models.ForeignKey):
                continue

            target_model = field.related_model
            if target_model.__name__ in _FK_TARGET_SKIPLIST:
                continue

            target_node_name = model_to_node_name.get(target_model)
            if target_node_name is None:
                continue
            target_node_id = _node_id(team_id, CatalogNode.Kind.SYSTEM_TABLE, target_node_name)
            if target_node_id is None:
                continue

            # `field.column` is the DB column name ("team_id"). `field.target_field.name`
            # is the target's column ("id" in nearly every case).
            source_column_id = _column_id(source_node_id, field.column)
            target_column_id = _column_id(target_node_id, field.target_field.name)

            CatalogAPI.propose_relationship(
                ProposeRelationshipParams(
                    team_id=team_id,
                    source_node_id=source_node_id,
                    target_node_id=target_node_id,
                    source_column_id=source_column_id,
                    target_column_id=target_column_id,
                    kind=CatalogRelationship.Kind.FOREIGN_KEY,
                    confidence=1.0,
                    reasoning=(f"Django ForeignKey: {source_model.__name__}.{field.name} → {target_model.__name__}"),
                )
            )
            count += 1

    return count


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


def _build_model_to_node_name() -> dict[type[models.Model], str]:
    """Map Django model classes to their SystemTables catalog node name.

    Walks `SystemTables().children`, pulls `postgres_table_name` from each
    PostgresTable entry, and resolves to a Django model via apps.get_model.
    Non-Postgres-backed entries (e.g. IngestionWarningsTable) are skipped.
    """
    out: dict[type[models.Model], str] = {}
    for catalog_name, child in SystemTables().children.items():
        table = child.table
        if not isinstance(table, PostgresTable):
            continue
        db_table = table.postgres_table_name
        if not db_table.startswith("posthog_"):
            continue
        model_name = db_table.removeprefix("posthog_")
        try:
            model = apps.get_model("posthog", model_name)
        except LookupError:
            continue
        out[model] = catalog_name
    return out


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
