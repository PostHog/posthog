from typing import Any

import dagster as dg
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from dags.common import JobOwners
from posthog.warehouse.models.table import DataWarehouseTable


class SnapshotConfig(dg.Config):
    team_id: int = 1
    chunk_size: int = 1000


def to_arrow(row_dicts: list[dict[str, Any]]):
    return pa.Table.from_pandas(pd.DataFrame(row_dicts), preserve_index=False)


@dg.asset
def dump_dwh_tables(config: SnapshotConfig):
    log = dg.get_dagster_logger()

    qs = DataWarehouseTable.objects.filter(team_id=config.team_id).values().iterator(chunk_size=1000)

    batch_rows = []
    writer = None

    for row in qs:
        batch_rows.append(row)

        # Initialize writer with schema from first batch
        if writer is None and len(batch_rows) >= config.chunk_size:
            table = to_arrow(batch_rows)
            writer = pq.ParquetWriter(config.output_path, table.schema)
            writer.write_table(table)
            batch_rows.clear()
        elif writer is not None and len(batch_rows) >= config.chunk_size:
            writer.write_table(to_arrow(batch_rows))
            batch_rows.clear()

    # Handle case where no rows found
    if writer is None:
        if not batch_rows:
            # Write empty parquet with no rows
            table = pa.table({})
            pq.write_table(table, config.output_path)
            log.info("No rows found; wrote empty parquet.")
            return dg.Output(config.output_path)
        else:
            # Less than chunk_size rows total
            table = to_arrow(batch_rows)
            writer = pq.ParquetWriter(config.output_path, table.schema)
            writer.write_table(table)
    elif batch_rows:
        # Write remaining rows
        writer.write_table(to_arrow(batch_rows))

    if writer:
        writer.close()

    log.info(f"Wrote {config.output_path}")
    return dg.Output(config.output_path)


snapshot_team_data_job = dg.define_asset_job(
    name="snapshot_team_data_job",
    selection=[dump_dwh_tables.key],
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
)
