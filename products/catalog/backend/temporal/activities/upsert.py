"""Upsert activities — write CatalogNode / CatalogColumn rows via the facade.

The workflow chunks enumeration output and calls `upsert_warehouse_batch` once
per chunk. The activity is idempotent (the facade `update_or_create`s on
natural keys), so retries and re-runs against the same warehouse don't
duplicate rows.
"""

import asyncio
from dataclasses import dataclass
from uuid import UUID

from temporalio import activity

from products.catalog.backend.facade.api import CatalogAPI
from products.catalog.backend.facade.contracts import UpsertColumnParams, UpsertNodeParams
from products.catalog.backend.models import CatalogNode
from products.catalog.backend.temporal.activities.enumerate import WarehouseTableRef


@dataclass
class BatchUpsertResult:
    nodes: int = 0
    columns: int = 0


@dataclass
class UpsertWarehouseBatchArgs:
    team_id: int
    tables: list[WarehouseTableRef]


@activity.defn
async def upsert_warehouse_batch(args: UpsertWarehouseBatchArgs) -> BatchUpsertResult:
    """Upsert one chunk of warehouse tables + their columns."""
    return await asyncio.to_thread(_upsert_warehouse_batch_sync, args)


def _upsert_warehouse_batch_sync(args: UpsertWarehouseBatchArgs) -> BatchUpsertResult:
    result = BatchUpsertResult()

    for table_ref in args.tables:
        node = CatalogAPI.upsert_node(
            UpsertNodeParams(
                team_id=args.team_id,
                kind=CatalogNode.Kind.WAREHOUSE_TABLE,
                name=table_ref.name,
                warehouse_table_id=UUID(table_ref.id),
            )
        )
        result.nodes += 1

        for position, column_ref in enumerate(table_ref.columns):
            CatalogAPI.upsert_column(
                UpsertColumnParams(
                    node_id=node.id,
                    name=column_ref.name,
                    position=position,
                    clickhouse_type=column_ref.clickhouse_type,
                    nullable=column_ref.nullable,
                )
            )
            result.columns += 1

    return result
