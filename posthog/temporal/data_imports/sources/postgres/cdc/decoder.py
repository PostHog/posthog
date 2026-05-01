"""pgoutput binary protocol decoder.

Parses the binary messages produced by PostgreSQL's pgoutput logical decoding
plugin, as returned by pg_logical_slot_peek_binary_changes(). Converts them
into database-agnostic ChangeEvent objects.

References:
- https://www.postgresql.org/docs/current/protocol-logicalrep-message-formats.html
- https://www.postgresql.org/docs/current/protocol-message-types.html

Message types handled:
  B (Begin)    - Start of a transaction
  C (Commit)   - End of a transaction; flushes buffered events
  R (Relation) - Schema metadata for a relation (table)
  I (Insert)   - New row
  U (Update)   - Updated row
  D (Delete)   - Deleted row
  T (Truncate) - Table truncated (logged as warning)
"""

from __future__ import annotations

import struct
import logging
from dataclasses import (
    dataclass,
    field,
    replace as dataclass_replace,
)
from datetime import UTC, datetime
from typing import Any

from posthog.temporal.data_imports.cdc.types import ChangeEvent
from posthog.temporal.data_imports.sources.postgres.cdc.position import PgLSN

logger = logging.getLogger(__name__)

# PostgreSQL epoch: 2000-01-01 00:00:00 UTC
# Timestamps in pgoutput are microseconds since this epoch
PG_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
PG_EPOCH_OFFSET_US = int(PG_EPOCH.timestamp() * 1_000_000)

# Common Postgres type OIDs for basic type casting
_OID_BOOL = 16
_OID_INT2 = 21
_OID_INT4 = 23
_OID_INT8 = 20
_OID_FLOAT4 = 700
_OID_FLOAT8 = 701
_OID_TEXT = 25
_OID_VARCHAR = 1043
_OID_NUMERIC = 1700
_OID_JSON = 114
_OID_JSONB = 3802


@dataclass
class RelationColumn:
    """A single column within a Relation message."""

    flags: int  # 1 = part of the key
    name: str
    type_oid: int
    type_modifier: int


@dataclass
class Relation:
    """Cached relation (table) metadata from an R message."""

    relation_id: int
    schema_name: str
    table_name: str
    replica_identity: int  # 0=default, 1=nothing, 2=full, 3=index
    columns: list[RelationColumn] = field(default_factory=list)


class PgOutputDecoder:
    """Stateful decoder for pgoutput binary messages.

    Maintains a relation cache (updated by R messages) and a transaction
    buffer (events collected between B and C messages). Events are only
    yielded when a Commit message is received, ensuring atomic transactions.

    Usage:
        decoder = PgOutputDecoder()
        for lsn_str, xid, data in rows_from_peek:
            events = decoder.decode_message(data, lsn_str)
            for event in events:
                process(event)
    """

    def __init__(self) -> None:
        self._relations: dict[int, Relation] = {}
        self._tx_buffer: list[ChangeEvent] = []
        self._tx_timestamp: datetime | None = None
        self._truncated_tables: list[str] = []
        self._last_commit_end_lsn: str | None = None

    def decode_message(self, data: bytes, lsn: str) -> list[ChangeEvent]:
        """Decode a single pgoutput binary message.

        Returns a list of ChangeEvents. Only non-empty on Commit messages
        (transaction boundary), when all buffered events are flushed.
        """
        if not data:
            return []

        msg_type = chr(data[0])
        payload = data[1:]

        if msg_type == "B":
            self._handle_begin(payload)
        elif msg_type == "C":
            return self._handle_commit(payload)
        elif msg_type == "R":
            self._handle_relation(payload)
        elif msg_type == "I":
            self._handle_insert(payload, lsn)
        elif msg_type == "U":
            self._handle_update(payload, lsn)
        elif msg_type == "D":
            self._handle_delete(payload, lsn)
        elif msg_type == "T":
            self._handle_truncate(payload)
        else:
            logger.debug("Ignoring unknown pgoutput message type: %s", msg_type)

        return []

    @property
    def truncated_tables(self) -> list[str]:
        """Tables that received a Truncate message. Caller should trigger re-snapshot."""
        return list(self._truncated_tables)

    def clear_truncated_tables(self) -> None:
        self._truncated_tables.clear()

    @property
    def last_commit_end_lsn(self) -> str | None:
        """End LSN of the most recently committed transaction.

        Set even for truncate-only transactions (which yield no ChangeEvents).
        Use this to advance the slot when no DML events were produced.
        """
        return self._last_commit_end_lsn

    # --- Message handlers ---

    def _handle_begin(self, payload: bytes) -> None:
        """B message: final_lsn(8) + timestamp(8) + xid(4)"""
        timestamp_us = struct.unpack("!q", payload[8:16])[0]
        # xid = struct.unpack("!I", payload[16:20])[0]  # not needed

        self._tx_timestamp = _pg_timestamp_to_datetime(timestamp_us)
        self._tx_buffer.clear()

    def _handle_commit(self, payload: bytes) -> list[ChangeEvent]:
        """C message: flags(1) + commit_lsn(8) + end_lsn(8) + timestamp(8)

        Flushes the transaction buffer. Events are stamped with end_lsn — the
        byte immediately after the commit record — so that confirm_position()
        advances past this transaction, not just to its start.
        """
        # end_lsn starts at byte 9: flags(1) + commit_lsn(8)
        end_lsn = PgLSN.from_bytes(payload[9:17]).serialize()
        self._last_commit_end_lsn = end_lsn
        events = [dataclass_replace(e, position_serialized=end_lsn) for e in self._tx_buffer]
        self._tx_buffer.clear()
        self._tx_timestamp = None
        return events

    def _handle_relation(self, payload: bytes) -> None:
        """R message: relation_id(4) + namespace(str) + name(str) + replica_identity(1) + n_cols(2) + columns"""
        offset = 0

        relation_id = struct.unpack("!I", payload[offset : offset + 4])[0]
        offset += 4

        schema_name, offset = _read_cstring(payload, offset)
        table_name, offset = _read_cstring(payload, offset)

        replica_identity = payload[offset]
        offset += 1

        n_cols = struct.unpack("!H", payload[offset : offset + 2])[0]
        offset += 2

        columns: list[RelationColumn] = []
        for _ in range(n_cols):
            flags = payload[offset]
            offset += 1

            col_name, offset = _read_cstring(payload, offset)

            type_oid = struct.unpack("!I", payload[offset : offset + 4])[0]
            offset += 4

            type_modifier = struct.unpack("!i", payload[offset : offset + 4])[0]
            offset += 4

            columns.append(
                RelationColumn(
                    flags=flags,
                    name=col_name,
                    type_oid=type_oid,
                    type_modifier=type_modifier,
                )
            )

        self._relations[relation_id] = Relation(
            relation_id=relation_id,
            schema_name=schema_name,
            table_name=table_name,
            replica_identity=replica_identity,
            columns=columns,
        )

    def _handle_insert(self, payload: bytes, lsn: str) -> None:
        """I message: relation_id(4) + 'N' + tuple_data"""
        relation_id = struct.unpack("!I", payload[0:4])[0]
        # payload[4] should be ord('N') = 78
        tuple_data = payload[5:]

        relation = self._get_relation(relation_id)
        if relation is None:
            return

        columns = _decode_tuple(tuple_data, relation)

        self._tx_buffer.append(
            ChangeEvent(
                operation="I",
                table_name=relation.table_name,
                position_serialized=lsn,
                timestamp=self._tx_timestamp or datetime.now(tz=UTC),
                columns=columns,
            )
        )

    def _handle_update(self, payload: bytes, lsn: str) -> None:
        """U message: relation_id(4) + ['K'|'O' + old_tuple] + 'N' + new_tuple

        The old tuple is optional (depends on REPLICA IDENTITY setting).
        We only need the new tuple for CDC upserts.
        """
        relation_id = struct.unpack("!I", payload[0:4])[0]
        offset = 4

        relation = self._get_relation(relation_id)
        if relation is None:
            return

        # Skip optional old key/old tuple
        marker = chr(payload[offset])
        if marker in ("K", "O"):
            offset += 1
            _, offset = _skip_tuple(payload, offset, relation)

        # New tuple starts with 'N'
        if chr(payload[offset]) != "N":
            logger.warning("Expected 'N' marker in Update message, got '%s'", chr(payload[offset]))
            return
        offset += 1

        columns = _decode_tuple(payload[offset:], relation)

        self._tx_buffer.append(
            ChangeEvent(
                operation="U",
                table_name=relation.table_name,
                position_serialized=lsn,
                timestamp=self._tx_timestamp or datetime.now(tz=UTC),
                columns=columns,
            )
        )

    def _handle_delete(self, payload: bytes, lsn: str) -> None:
        """D message: relation_id(4) + 'K'|'O' + old_tuple

        Delete messages include the old key columns (or full row if
        REPLICA IDENTITY FULL). We decode them so the merge-by-PK
        can match the row.
        """
        relation_id = struct.unpack("!I", payload[0:4])[0]
        offset = 4

        relation = self._get_relation(relation_id)
        if relation is None:
            return

        # marker is 'K' (key columns) or 'O' (old full row)
        # marker = chr(payload[offset])
        offset += 1

        columns = _decode_tuple(payload[offset:], relation)

        self._tx_buffer.append(
            ChangeEvent(
                operation="D",
                table_name=relation.table_name,
                position_serialized=lsn,
                timestamp=self._tx_timestamp or datetime.now(tz=UTC),
                columns=columns,
            )
        )

    def _handle_truncate(self, payload: bytes) -> None:
        """T message: n_relations(4) + option_flags(1) + relation_ids(4*n)"""
        n_relations = struct.unpack("!I", payload[0:4])[0]
        # option_flags = payload[4]  # 1=CASCADE, 2=RESTART IDENTITY
        offset = 5

        for _ in range(n_relations):
            relation_id = struct.unpack("!I", payload[offset : offset + 4])[0]
            offset += 4
            relation = self._relations.get(relation_id)
            if relation:
                logger.warning(
                    "Received TRUNCATE for table %s.%s — marking for re-snapshot",
                    relation.schema_name,
                    relation.table_name,
                )
                self._truncated_tables.append(relation.table_name)

    # --- Helpers ---

    def get_key_columns(self, table_name: str) -> list[str]:
        """Return column names that are part of the replica identity key for a table."""
        for relation in self._relations.values():
            if relation.table_name == table_name:
                return [col.name for col in relation.columns if col.flags & 1]
        return []

    def _get_relation(self, relation_id: int) -> Relation | None:
        relation = self._relations.get(relation_id)
        if relation is None:
            logger.warning("Received event for unknown relation_id %d — missing R message?", relation_id)
        return relation


def _read_cstring(data: bytes, offset: int) -> tuple[str, int]:
    """Read a null-terminated C string from data starting at offset."""
    end = data.index(0, offset)
    return data[offset:end].decode("utf-8"), end + 1


def _decode_tuple(data: bytes, relation: Relation) -> dict[str, Any]:
    """Decode a pgoutput tuple into a dict of column_name → Python value.

    Tuple format: n_cols(2) + for each column: type_byte + [data]
      - 'n': NULL
      - 'u': unchanged TOAST value (skipped)
      - 't': text value → int32 length + UTF-8 bytes
    """
    offset = 0
    n_cols = struct.unpack("!H", data[offset : offset + 2])[0]
    offset += 2

    columns: dict[str, Any] = {}

    for i in range(n_cols):
        if i >= len(relation.columns):
            break

        col_meta = relation.columns[i]
        col_type = chr(data[offset])
        offset += 1

        if col_type == "n":
            columns[col_meta.name] = None
        elif col_type == "u":
            # Unchanged TOAST — value not sent. Skip.
            pass
        elif col_type == "t":
            length = struct.unpack("!I", data[offset : offset + 4])[0]
            offset += 4
            text_value = data[offset : offset + length].decode("utf-8")
            offset += length
            columns[col_meta.name] = _cast_text_value(text_value, col_meta.type_oid)
        else:
            logger.warning("Unknown tuple column type '%s' for column %s", col_type, col_meta.name)

    return columns


def _skip_tuple(data: bytes, offset: int, relation: Relation) -> tuple[dict[str, Any], int]:
    """Skip over a tuple in the payload, returning the new offset.

    Also decodes and returns the tuple data (useful for old key in updates).
    """
    n_cols = struct.unpack("!H", data[offset : offset + 2])[0]
    start = offset
    offset += 2

    for _ in range(n_cols):
        col_type = chr(data[offset])
        offset += 1

        if col_type == "n":
            pass
        elif col_type == "u":
            pass
        elif col_type == "t":
            length = struct.unpack("!I", data[offset : offset + 4])[0]
            offset += 4 + length

    # Decode the tuple we just skipped for return value
    columns = _decode_tuple(data[start:offset], relation)
    return columns, offset


def _cast_text_value(text: str, type_oid: int) -> Any:
    """Cast a pgoutput text-format value to a Python type based on OID.

    pgoutput always sends values in text format. We cast common types
    to their Python equivalents. Unknown types are left as strings.
    """
    if type_oid == _OID_BOOL:
        return text == "t"
    elif type_oid in (_OID_INT2, _OID_INT4, _OID_INT8):
        return int(text)
    elif type_oid in (_OID_FLOAT4, _OID_FLOAT8):
        return float(text)
    elif type_oid == _OID_NUMERIC:
        # Keep as string to preserve precision (Decimal-like)
        return text
    elif type_oid in (_OID_JSON, _OID_JSONB):
        # Keep as string — let downstream handle JSON parsing
        return text
    else:
        return text


def _pg_timestamp_to_datetime(us_since_pg_epoch: int) -> datetime:
    """Convert microseconds since PostgreSQL epoch (2000-01-01) to a datetime."""
    unix_us = us_since_pg_epoch + PG_EPOCH_OFFSET_US
    return datetime.fromtimestamp(unix_us / 1_000_000, tz=UTC)
