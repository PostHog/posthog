"""SQL-based CDC stream reader for PostgreSQL.

Uses pg_logical_slot_peek_binary_changes() to read WAL changes via a regular
SQL connection (not the streaming replication protocol). This is the Option E
approach — batch reads on a schedule.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import psycopg
from psycopg import sql

from posthog.temporal.data_imports.cdc.types import ChangeEvent
from posthog.temporal.data_imports.sources.postgres.cdc.decoder import PgOutputDecoder
from posthog.temporal.data_imports.sources.postgres.postgres import _connect_to_postgres, get_primary_key_columns

if TYPE_CHECKING:
    from products.data_warehouse.backend.models import ExternalDataSource

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PgCDCConnectionParams:
    host: str
    port: int
    database: str
    user: str
    password: str
    sslmode: str = "prefer"
    slot_name: str = ""
    publication_name: str = ""


class PgCDCStreamReader:
    """Reads WAL changes from a PostgreSQL replication slot using SQL queries.

    Uses pg_logical_slot_peek_binary_changes() for non-destructive reads
    and pg_replication_slot_advance() for explicit position confirmation.

    SSH tunneling: when ``source`` is provided, ``connect()`` opens an SSH tunnel
    via ``PostgresSource.with_ssh_tunnel`` and rewrites the connection host/port to
    the local tunnel endpoint. The tunnel stays open until ``close()`` is called,
    so both the streaming cursor and short-lived ``confirm_position`` connections
    use the same tunnel.
    """

    def __init__(self, params: PgCDCConnectionParams, source: ExternalDataSource | None = None) -> None:
        self._params = params
        self._source = source
        self._conn: psycopg.Connection | None = None
        self._decoder = PgOutputDecoder()
        self._tunnel_cm: AbstractContextManager[tuple[str, int]] | None = None
        self._effective_host: str = params.host
        self._effective_port: int = params.port

    def connect(self) -> None:
        # If a source is provided, enter the SSH tunnel context (no-op if SSH is disabled).
        # The tunnel must stay open for the lifetime of the reader so confirm_position
        # connections can also reach the source DB.
        if self._source is not None:
            from posthog.temporal.data_imports.sources.postgres.source import PostgresSource

            source_impl = PostgresSource()
            config = source_impl.parse_config(self._source.job_inputs or {})
            tunnel_cm = source_impl.with_ssh_tunnel(config)
            self._effective_host, self._effective_port = tunnel_cm.__enter__()
            self._tunnel_cm = tunnel_cm

        self._conn = _connect_to_postgres(
            host=self._effective_host,
            port=self._effective_port,
            database=self._params.database,
            user=self._params.user,
            password=self._params.password,
        )

    def read_changes(self) -> Iterator[ChangeEvent]:
        """Read all pending WAL changes from the replication slot.

        Uses peek (non-consuming) so the slot position is not advanced.
        Call confirm_position() after successful processing.

        Uses a named server-side cursor to stream rows in chunks rather than
        buffering the entire WAL backlog in client memory.
        """
        if self._conn is None:
            raise RuntimeError("Not connected. Call connect() first.")

        query = sql.SQL(
            "SELECT lsn, xid, data FROM pg_logical_slot_peek_binary_changes("
            "{slot_name}, NULL, NULL, "
            "'proto_version', '1', "
            "'publication_names', {pub_name}"
            ")"
        ).format(
            slot_name=sql.Literal(self._params.slot_name),
            pub_name=sql.Literal(self._params.publication_name),
        )

        with self._conn.cursor(name="cdc_stream") as cur:
            cur.itersize = 1000
            cur.execute(query)

            for row in cur:
                lsn_str: str = row[0]
                data: bytes = row[2]

                events = self._decoder.decode_message(data, lsn_str)
                yield from events

    def confirm_position(self, position: str) -> None:
        """Advance the replication slot to the given LSN.

        This consumes all WAL up to and including the given position.
        Safe to call mid-iteration of ``read_changes()`` because it opens its own
        short-lived connection rather than reusing the streaming cursor's connection
        (which can't run other queries while the named server-side cursor is active).
        """
        query = sql.SQL("SELECT pg_replication_slot_advance({slot_name}, {lsn})").format(
            slot_name=sql.Literal(self._params.slot_name),
            lsn=sql.Literal(position),
        )

        advance_conn = _connect_to_postgres(
            host=self._effective_host,
            port=self._effective_port,
            database=self._params.database,
            user=self._params.user,
            password=self._params.password,
        )
        try:
            with advance_conn.cursor() as cur:
                cur.execute(query)
            advance_conn.commit()
        finally:
            advance_conn.close()

        logger.info("Advanced slot %s to position %s", self._params.slot_name, position)

    def get_primary_key_columns(self, schema_name: str, table_names: list[str]) -> dict[str, list[str]]:
        """Query information_schema for PK columns of the given tables.

        Returns a dict of table_name → list of PK column names.
        """
        if self._conn is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return get_primary_key_columns(self._conn, schema_name, table_names)

    @property
    def truncated_tables(self) -> list[str]:
        """Tables that received a TRUNCATE during the last read_changes() call."""
        return self._decoder.truncated_tables

    def clear_truncated_tables(self) -> None:
        self._decoder.clear_truncated_tables()

    def get_decoder_key_columns(self, table_name: str) -> list[str]:
        """Return PK columns discovered by the decoder from Relation messages during read_changes()."""
        return self._decoder.get_key_columns(table_name)

    @property
    def last_commit_end_lsn(self) -> str | None:
        """End LSN of the most recently committed transaction.

        Non-None even when only TRUNCATE messages were decoded (no ChangeEvents).
        Use this to advance the slot when event_count == 0 but truncates occurred.
        """
        return self._decoder.last_commit_end_lsn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        if self._tunnel_cm is not None:
            self._tunnel_cm.__exit__(None, None, None)
            self._tunnel_cm = None
