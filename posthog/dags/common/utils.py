import json
import hashlib

import polars as pl


def compute_dataframe_hashes(df: pl.DataFrame) -> pl.DataFrame:
    """Add a data_hash column for incremental change detection.

    Each row is serialized to a deterministic JSON string and hashed with SHA-256,
    truncated to 16 hex characters. Pipelines compare these hashes against prior
    materialization metadata to skip unchanged records.
    """

    def row_hash(row: dict) -> str:
        serialized = json.dumps(row, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]

    hashes = [row_hash(row) for row in df.to_dicts()]
    return df.with_columns(pl.Series("data_hash", hashes))
