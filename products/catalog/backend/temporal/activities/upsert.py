"""Upsert activities — write CatalogNode / CatalogColumn rows via the facade.

The workflow chunks enumeration output and calls `upsert_node_batch` once per
chunk. The activity is idempotent (the facade `update_or_create`s on natural
keys), so retries and re-runs against the same source don't duplicate rows.

The same activity handles every node kind — the ref carries the kind plus the
optional backing-row id (for kinds bound via the GFK on CatalogNode).
"""

import asyncio
from dataclasses import dataclass
from uuid import UUID

from temporalio import activity

from products.catalog.backend.facade.api import CatalogAPI
from products.catalog.backend.facade.contracts import UpsertColumnParams, UpsertNodeParams
from products.catalog.backend.models import CatalogNode
from products.catalog.backend.temporal.activities.enumerate import CatalogNodeRef


@dataclass
class BatchUpsertResult:
    nodes: int = 0
    columns: int = 0


@dataclass
class UpsertNodeBatchArgs:
    team_id: int
    refs: list[CatalogNodeRef]


@activity.defn
async def upsert_node_batch(args: UpsertNodeBatchArgs) -> BatchUpsertResult:
    """Upsert one chunk of catalog nodes + their columns, regardless of kind."""
    return await asyncio.to_thread(_upsert_node_batch_sync, args)


def _upsert_node_batch_sync(args: UpsertNodeBatchArgs) -> BatchUpsertResult:
    result = BatchUpsertResult()

    for ref in args.refs:
        warehouse_table_id: UUID | None = None
        saved_query_id: UUID | None = None
        if ref.id is not None:
            backing_id = UUID(ref.id)
            if ref.kind == CatalogNode.Kind.WAREHOUSE_TABLE:
                warehouse_table_id = backing_id
            elif ref.kind == CatalogNode.Kind.SAVED_QUERY:
                saved_query_id = backing_id
            # Other kinds (system_table, posthog_table) currently have no
            # backing-row binding even when an id is provided — leave both null.

        node = CatalogAPI.upsert_node(
            UpsertNodeParams(
                team_id=args.team_id,
                kind=ref.kind,
                name=ref.name,
                warehouse_table_id=warehouse_table_id,
                saved_query_id=saved_query_id,
            )
        )
        result.nodes += 1

        for position, column_ref in enumerate(ref.columns):
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
