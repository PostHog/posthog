"""Postgres CDC adapter using pgoutput logical replication."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal

from posthog.temporal.data_imports.sources.postgres.cdc.config import PostgresCDCConfig

if TYPE_CHECKING:
    from posthog.temporal.data_imports.cdc.types import CDCStreamReader

    from products.data_warehouse.backend.models import ExternalDataSource


class PostgresCDCAdapter:
    def parse_cdc_config(self, source: ExternalDataSource) -> PostgresCDCConfig:
        return PostgresCDCConfig.from_source(source)

    def create_reader(self, source: ExternalDataSource) -> CDCStreamReader:
        from posthog.temporal.data_imports.sources.postgres.cdc.stream_reader import (
            PgCDCConnectionParams,
            PgCDCStreamReader,
        )

        inputs = source.job_inputs or {}
        cdc_config = self.parse_cdc_config(source)
        params = PgCDCConnectionParams(
            host=inputs.get("host", ""),
            port=int(inputs.get("port", 5432)),
            database=inputs.get("database", ""),
            user=inputs.get("user", ""),
            password=inputs.get("password", ""),
            sslmode=inputs.get("sslmode", "prefer"),
            slot_name=cdc_config.slot_name,
            publication_name=cdc_config.publication_name,
        )
        return PgCDCStreamReader(params, source=source)

    @contextmanager
    def management_connection(self, source: ExternalDataSource, connect_timeout: int = 15) -> Iterator[Any]:
        from posthog.temporal.data_imports.sources.postgres.cdc.slot_manager import cdc_pg_connection

        with cdc_pg_connection(source, connect_timeout=connect_timeout) as conn:
            yield conn

    def validate_prerequisites(
        self,
        source: ExternalDataSource,
        management_mode: Literal["posthog", "self_managed"],
        tables: list[str],
        schema: str,
        slot_name: str | None,
        publication_name: str | None,
    ) -> list[str]:
        from posthog.temporal.data_imports.sources.postgres.cdc.prerequisite_validator import validate_cdc_prerequisites

        with self.management_connection(source) as conn:
            return validate_cdc_prerequisites(
                conn=conn,
                management_mode=management_mode,
                tables=tables,
                schema=schema,
                slot_name=slot_name,
                publication_name=publication_name,
            )

    def drop_resources(self, conn: Any, slot_name: str, pub_name: str) -> None:
        from posthog.temporal.data_imports.sources.postgres.cdc.slot_manager import drop_slot_and_publication

        drop_slot_and_publication(conn, slot_name, pub_name)

    def get_lag_bytes(self, conn: Any, slot_name: str) -> int | None:
        from posthog.temporal.data_imports.sources.postgres.cdc.slot_manager import get_slot_lag_bytes

        return get_slot_lag_bytes(conn, slot_name)
