"""Seeder hook that installs a synthetic data warehouse into a per-case team.

Translates the pure ``WarehouseSchemaSynthesizer`` output into ORM rows:
hundreds of self-managed ``DataWarehouseTable`` metadata rows (no S3 needed to be
*discoverable*), their table/column annotations, the data-modeling views, and the
join relationships. The one queryable "duck typing" needle is created best-effort
via CSV upload to object storage — if that environment isn't available the seed
still succeeds and records ``queryable=False`` so its scorer self-skips.

Runs synchronously in a worker thread (``asyncio.to_thread``) from
``base.py:task()`` after the per-case team is provisioned; the returned dict is
merged into the task output under ``seed`` for scorers.
"""

from __future__ import annotations

import csv
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ee.hogai.eval.sandboxed.data_warehouse.synthesizer import (
    DESC_NEEDLE_PHRASE,
    DESC_NEEDLE_TABLE,
    REL_NEEDLE_FIELD,
    REL_NEEDLE_KEY,
    REL_NEEDLE_SOURCE,
    REL_NEEDLE_TARGET,
    RETRIEVAL_NEEDLE_ANSWER,
    RETRIEVAL_NEEDLE_EVENT_ID,
    RETRIEVAL_NEEDLE_PREFIX,
    TYPE_NEEDLE_COLUMN,
    TYPE_NEEDLE_DATA_TYPE,
    TYPE_NEEDLE_TABLE,
    VIEW_NEEDLE_NAME,
    SynthTable,
    WarehouseSchemaSynthesizer,
)

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.tasks.backend.facade.agents import CustomPromptSandboxContext

logger = logging.getLogger(__name__)

__all__ = ["seed_warehouse_schema"]


def seed_warehouse_schema(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed a synthetic warehouse: ~250 metadata tables, annotations, views, joins,
    and one best-effort queryable CSV needle. Returns the ``seed`` dict scorers read."""
    from posthog.models.scoping import team_scope
    from posthog.models.team import Team

    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
    from products.data_tools.backend.models.join import DataWarehouseJoin
    from products.warehouse_sources.backend.models.column_annotation import WarehouseColumnAnnotation
    from products.warehouse_sources.backend.models.table import DataWarehouseTable

    team = Team.objects.get(pk=context.team_id)
    user_id = context.user_id
    warehouse = WarehouseSchemaSynthesizer().generate()

    # 1. Metadata tables. Self-managed (no external_data_source / credential) so they
    #    register under their literal name and surface in information_schema without S3.
    metadata_tables = [t for t in warehouse.tables if not t.queryable]
    table_models = {
        t.name: DataWarehouseTable(
            team=team,
            name=t.name,
            format=DataWarehouseTable.TableFormat.CSVWithNames,
            url_pattern="",
            columns=t.columns_json(),
            row_count=t.row_count,
            credential=None,
        )
        for t in metadata_tables
    }
    DataWarehouseTable.objects.bulk_create(list(table_models.values()), batch_size=200)

    # 2. Annotations — table-level (column_name="") and column-level — under team_scope.
    #    UUIDTModel ids are generated client-side, so the in-memory models carry valid pks.
    annotations: list[WarehouseColumnAnnotation] = []
    source = WarehouseColumnAnnotation.DescriptionSource.CANONICAL
    for t in metadata_tables:
        model = table_models[t.name]
        if t.description:
            annotations.append(
                WarehouseColumnAnnotation(
                    team=team, table=model, column_name="", description=t.description, description_source=source
                )
            )
        for column in t.columns:
            if column.description:
                annotations.append(
                    WarehouseColumnAnnotation(
                        team=team,
                        table=model,
                        column_name=column.name,
                        description=column.description,
                        description_source=source,
                    )
                )
    with team_scope(team.id, canonical=True):
        WarehouseColumnAnnotation.objects.bulk_create(annotations, batch_size=200)

    # 3. Views ("models").
    for view in warehouse.views:
        DataWarehouseSavedQuery.objects.create(
            team=team,
            created_by_id=user_id,
            name=view.name,
            columns=view.columns_json(),
            query={"query": view.sql},
            status=DataWarehouseSavedQuery.Status.COMPLETED,
        )

    # 4. Joins — both endpoint tables already exist, keys are bare column names.
    for join in warehouse.joins:
        DataWarehouseJoin.objects.create(
            team=team,
            source_table_name=join.source_table,
            source_table_key=join.source_key,
            joining_table_name=join.joining_table,
            joining_table_key=join.joining_key,
            field_name=join.field_name,
        )

    # 5. Queryable retrieval needle — best-effort; never fail the seed.
    retrieval_table = next((t for t in warehouse.tables if t.queryable), None)
    retrieval_meta: dict[str, Any] = {"queryable": False, "answer": RETRIEVAL_NEEDLE_ANSWER}
    if retrieval_table is not None:
        retrieval_meta = _create_queryable_needle(team, retrieval_table)

    payload: dict[str, Any] = {
        "table_count": len(metadata_tables) + (1 if retrieval_meta.get("queryable") else 0),
        "view_count": len(warehouse.views),
        "join_count": len(warehouse.joins),
        "description_needle": {"table": DESC_NEEDLE_TABLE, "phrase": DESC_NEEDLE_PHRASE},
        "column_type_needle": {
            "table": TYPE_NEEDLE_TABLE,
            "column": TYPE_NEEDLE_COLUMN,
            "data_type": TYPE_NEEDLE_DATA_TYPE,
        },
        "relationship_needle": {
            "source": REL_NEEDLE_SOURCE,
            "target": REL_NEEDLE_TARGET,
            "key": REL_NEEDLE_KEY,
            "field_name": REL_NEEDLE_FIELD,
        },
        "view_needle": {"name": VIEW_NEEDLE_NAME},
        "retrieval_needle": retrieval_meta,
    }
    logger.info(
        "Seeded synthetic warehouse for team_id=%s: %d tables, %d views, %d joins (retrieval queryable=%s)",
        team.id,
        payload["table_count"],
        payload["view_count"],
        payload["join_count"],
        retrieval_meta.get("queryable"),
    )
    return payload


def _create_queryable_needle(team: Team, table: SynthTable) -> dict[str, Any]:
    """Upload the needle's CSV to object storage and register a queryable table.

    Returns ``queryable=False`` (and logs) on any failure — object storage may be
    unavailable in the harness, in which case the retrieval scorer self-skips and
    the other four needles (metadata-only) are unaffected.
    """
    from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv

    try:
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([column.name for column in table.columns])
            for row in table.rows:
                writer.writerow(row)
            csv_path = Path(handle.name)

        created, *_rest = create_data_warehouse_table_from_csv(
            csv_path=csv_path,
            table_name=table.name,
            table_columns={column.name: column.clickhouse_base for column in table.columns},
            test_bucket="eval_warehouse",
            team=team,
            source_prefix=RETRIEVAL_NEEDLE_PREFIX,
        )
        return {
            "queryable": True,
            "table": created.name,
            "answer": RETRIEVAL_NEEDLE_ANSWER,
            "event_id": RETRIEVAL_NEEDLE_EVENT_ID,
        }
    except Exception:
        logger.exception("Queryable needle creation failed; degrading retrieval needle to metadata-only")
        return {"queryable": False, "answer": RETRIEVAL_NEEDLE_ANSWER, "event_id": RETRIEVAL_NEEDLE_EVENT_ID}
