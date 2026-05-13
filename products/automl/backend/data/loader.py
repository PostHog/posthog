"""Thin DuckDB-backed loader for parquet (local + S3) and ad hoc SQL.

Mirrors the S3 secret pattern from ``posthog/ducklake/storage.py`` but stays
scoped to plain parquet I/O — no DuckLake / Delta extensions. If we later want
to land predictions into a team's DuckLake catalog, swap this for
``posthog.ducklake.storage.configure_connection`` and ``attach_catalog``.

ClickHouse is intentionally out of scope: there's no first-class DuckDB
ClickHouse scanner. The expected path is "export CH events to parquet, then
point this loader at the parquet" — or fall back to ``posthog.client`` for
ad hoc CH SQL outside the AutoML pipeline.
"""

from __future__ import annotations

from types import TracebackType
from typing import Optional

import duckdb
import polars as pl
import structlog

logger = structlog.get_logger(__name__)


class DataLoader:
    """Single-connection DuckDB wrapper that returns Polars frames."""

    def __init__(
        self,
        *,
        s3_region: Optional[str] = None,
        s3_endpoint: Optional[str] = None,
        postgres_connection: Optional[str] = None,
    ) -> None:
        logger.info(
            "duckdb_connect_start", s3_region=s3_region, s3_endpoint=s3_endpoint, has_postgres=bool(postgres_connection)
        )
        self.con = duckdb.connect()
        self.con.execute("INSTALL httpfs")
        self.con.execute("LOAD httpfs")

        secret_parts = ["TYPE S3", "PROVIDER credential_chain"]
        if s3_region:
            secret_parts.append(f"REGION '{s3_region}'")
        if s3_endpoint:
            secret_parts.append(f"ENDPOINT '{s3_endpoint}'")
        try:
            self.con.execute(f"CREATE OR REPLACE SECRET automl_s3 ({', '.join(secret_parts)})")
            logger.debug("s3_secret_created", region=s3_region, endpoint=s3_endpoint)
        except duckdb.Error as exc:
            logger.warning("s3_secret_create_failed", error=str(exc))

        if postgres_connection:
            self.con.execute("INSTALL postgres")
            self.con.execute("LOAD postgres")
            self.con.execute("ATTACH ? AS pg (TYPE POSTGRES, READ_ONLY)", [postgres_connection])
            logger.info("postgres_attached", alias="pg")
        logger.info("duckdb_connect_ready")

    def query(self, sql: str, params: Optional[list[object]] = None) -> pl.DataFrame:
        """Run a SQL query and return a Polars DataFrame."""
        cursor = self.con.execute(sql, params) if params else self.con.execute(sql)
        return cursor.pl()

    def read_parquet(
        self,
        path: str,
        *,
        where: Optional[str] = None,
        columns: Optional[list[str]] = None,
    ) -> pl.DataFrame:
        """Read parquet from a local path or s3:// URL.

        ``where`` is appended as a raw SQL WHERE clause and is the caller's
        responsibility to sanitize. ``columns``, if provided, are validated
        against an identifier allowlist.
        """
        cols = "*"
        if columns:
            for col in columns:
                if not col.replace("_", "a").isalnum():
                    raise ValueError(f"Unsupported column identifier: {col!r}")
            cols = ", ".join(columns)
        sql = f"SELECT {cols} FROM read_parquet(?)"
        if where:
            sql += f" WHERE {where}"
        logger.info("read_parquet_start", path=path, columns=columns, has_where=bool(where))
        df = self.query(sql, [path])
        logger.info("read_parquet_done", path=path, rows=len(df), cols=len(df.columns))
        return df

    def write_parquet(self, df: pl.DataFrame, path: str, *, compression: str = "zstd") -> None:
        """Write a Polars DataFrame to parquet at a local path or s3:// URL."""
        logger.info("write_parquet_start", path=path, rows=len(df), cols=len(df.columns), compression=compression)
        arrow_table = df.to_arrow()
        self.con.register("_df_write_buffer", arrow_table)
        try:
            self.con.execute(f"COPY _df_write_buffer TO '{path}' (FORMAT PARQUET, COMPRESSION {compression})")
        finally:
            self.con.unregister("_df_write_buffer")
        logger.info("write_parquet_done", path=path, rows=len(df))

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> DataLoader:
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()
