"""Postgres CDC adapter using pgoutput logical replication."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal

from posthog.temporal.data_imports.sources.postgres.cdc.config import PostgresCDCConfig
from posthog.temporal.data_imports.sources.postgres.cdc.slot_manager import (
    cdc_pg_connection,
    create_slot,
    create_slot_and_publication,
    drop_slot,
    drop_slot_and_publication,
    get_slot_lag_bytes,
    publication_exists,
    slot_exists,
)

if TYPE_CHECKING:
    from posthog.temporal.data_imports.cdc.types import CDCStreamReader

    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

logger = logging.getLogger(__name__)


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
        drop_slot_and_publication(conn, slot_name, pub_name)

    def get_lag_bytes(self, conn: Any, slot_name: str) -> int | None:
        return get_slot_lag_bytes(conn, slot_name)

    def setup_resources(
        self,
        source: ExternalDataSource,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str | None]:
        """Create the logical replication slot (and the publication, for PostHog-managed
        mode) on the source database. Returns the cdc_* fields the caller should merge
        into ``source.job_inputs``, or an error string. Cleans up partial state on failure.
        """
        management_mode: Literal["posthog", "self_managed"] = (
            "self_managed" if payload.get("cdc_management_mode") == "self_managed" else "posthog"
        )
        slot_name = payload.get("cdc_slot_name") or f"posthog_{source.id.hex[:12]}"
        default_pub_name = "posthog_pub" if management_mode == "self_managed" else f"posthog_pub_{source.id.hex[:12]}"
        pub_name = payload.get("cdc_publication_name") or default_pub_name

        schema = self._resolve_schema(source)

        resource_fields: dict[str, Any] = {
            "cdc_management_mode": management_mode,
            "cdc_slot_name": slot_name,
            "cdc_publication_name": pub_name,
        }

        if management_mode == "posthog":
            try:
                with cdc_pg_connection(source) as conn:
                    resource_fields["cdc_consistent_point"] = create_slot_and_publication(
                        conn, slot_name, pub_name, schema, tables=[]
                    )
            except Exception as e:
                logger.exception("Failed to create CDC slot and publication: %s", e)
                # Best-effort rollback — `create_slot_and_publication` commits the
                # publication before creating the slot, so a slot failure leaves a
                # leaked publication. `drop_slot_and_publication` swallows
                # UndefinedObject, so it's a no-op when neither was created.
                try:
                    with cdc_pg_connection(source, connect_timeout=10) as conn:
                        drop_slot_and_publication(conn, slot_name, pub_name)
                except Exception as rollback_error:
                    logger.exception("Failed to roll back partial CDC slot/publication: %s", rollback_error)
                return {}, f"Failed to create replication slot: {e}"
            return resource_fields, None

        # self_managed
        try:
            with cdc_pg_connection(source) as conn:
                if not publication_exists(conn, pub_name):
                    return (
                        {},
                        (
                            f"Publication '{pub_name}' does not exist. Run the CREATE PUBLICATION "
                            f"statement we showed you, then retry."
                        ),
                    )
                resource_fields["cdc_consistent_point"] = create_slot(conn, slot_name)
        except Exception as e:
            logger.exception("Failed to set up self-managed CDC slot: %s", e)
            # Self-managed: drop only the slot — publication is customer-owned.
            try:
                with cdc_pg_connection(source, connect_timeout=10) as conn:
                    drop_slot(conn, slot_name)
            except Exception as rollback_error:
                logger.exception("Failed to roll back partial self-managed CDC slot: %s", rollback_error)
            return {}, f"Failed to create replication slot: {e}"
        return resource_fields, None

    def cleanup_resources(self, source: ExternalDataSource) -> None:
        """Drop the PostHog-managed replication slot (and publication, for PostHog-managed
        mode) on the source database. Self-managed mode drops only the slot — the
        publication is customer-owned. Best-effort: logs and continues on errors.
        """
        cdc_config = self.parse_cdc_config(source)
        if not cdc_config.enabled or not cdc_config.slot_name:
            return
        try:
            with cdc_pg_connection(source, connect_timeout=10) as conn:
                if cdc_config.management_mode == "self_managed":
                    drop_slot(conn, cdc_config.slot_name)
                elif cdc_config.publication_name:
                    drop_slot_and_publication(conn, cdc_config.slot_name, cdc_config.publication_name)
        except Exception:
            logger.exception(
                "Failed to drop CDC slot/publication on source DB (best-effort), source_id=%s slot=%s",
                source.id,
                cdc_config.slot_name,
            )

    def get_status(self, source: ExternalDataSource) -> dict[str, Any]:
        """Read live slot/publication existence and WAL lag from the source DB."""
        cdc_config = self.parse_cdc_config(source)
        with cdc_pg_connection(source, connect_timeout=10) as conn:
            slot_present = slot_exists(conn, cdc_config.slot_name) if cdc_config.slot_name else False
            pub_present = (
                publication_exists(conn, cdc_config.publication_name) if cdc_config.publication_name else False
            )
            lag_bytes = get_slot_lag_bytes(conn, cdc_config.slot_name) if cdc_config.slot_name else None
        return {
            "slot_exists": slot_present,
            "publication_exists": pub_present,
            "lag_bytes": lag_bytes,
        }

    def _resolve_schema(self, source: ExternalDataSource) -> str:
        raw = (source.job_inputs or {}).get("schema")
        return raw.strip() if isinstance(raw, str) and raw.strip() else "public"
