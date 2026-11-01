"""A Redshift-specific transformer that turns record batches into INSERT INTO queries."""

import json
import typing
import collections.abc

import pyarrow as pa
from psycopg import sql

from posthog.temporal.common.arrow_pipeline.transformer import Chunk


class RedshiftQueryStreamTransformer:
    """A transformer to convert record batches into a Redshift INSERT INTO query."""

    def __init__(
        self,
        schema: pa.Schema,
        redshift_table: str,
        redshift_schema: str | None,
        table_columns: collections.abc.Sequence[str],
        known_json_columns: collections.abc.Iterable[str],
        redshift_client,
        max_query_size_bytes: int = 8 * 1024 * 1024,
    ):
        self.schema = schema
        self.redshift_table = redshift_table
        self.redshift_schema = redshift_schema
        self.table_columns = list(table_columns)
        self.known_json_columns = known_json_columns
        self.redshift_client = redshift_client
        self.max_query_size_bytes = max_query_size_bytes

        placeholders: list[sql.Composable] = []
        for column in table_columns:
            placeholders.append(sql.Placeholder(column))

        self.template = sql.SQL("({})").format(sql.SQL(", ").join(placeholders))

    async def iter(
        self,
        record_batches: collections.abc.AsyncIterable[pa.RecordBatch],
    ) -> collections.abc.AsyncIterator[Chunk]:
        """Iterate over record batches transforming them into chunks."""
        current_file_size = 0

        query_start = await self.get_encoded_query_start()
        is_query_start = True

        async for record_batch in record_batches:
            for record in record_batch.select(self.table_columns).to_pylist():
                for json_column in self.known_json_columns:
                    if record.get(json_column, None) is None:
                        continue

                    record[json_column] = json.dumps(
                        remove_escaped_whitespace_recursive(record[json_column]), ensure_ascii=False
                    )

                chunk = await self.mogrify_record(record)

                if is_query_start:
                    yield Chunk(query_start, False)
                    is_query_start = False

                else:
                    yield Chunk(b",", False)

                yield Chunk(chunk, False)

                if current_file_size + len(chunk) > self.max_query_size_bytes:
                    yield Chunk(b"", True)
                    current_file_size = 0
                    is_query_start = True

                else:
                    current_file_size += len(chunk)

        yield Chunk(b"", True)

    async def mogrify_record(self, record: dict[str, typing.Any]) -> bytes:
        """Produce encoded bytes from a record."""
        async with self.redshift_client.async_client_cursor() as cursor:
            return cursor.mogrify(self.template, record).encode("utf-8").replace(b" E'", b" '")

    async def get_encoded_query_start(self) -> bytes:
        """Encode and format the start of an INSERT INTO query."""
        if self.redshift_schema:
            table_identifier = sql.Identifier(self.redshift_schema, self.redshift_table)
        else:
            table_identifier = sql.Identifier(self.redshift_table)

        pre_query = sql.SQL("INSERT INTO {table} ({fields}) VALUES").format(
            table=table_identifier,
            fields=sql.SQL(", ").join(map(sql.Identifier, self.table_columns)),
        )

        async with self.redshift_client.async_client_cursor() as cursor:
            return pre_query.as_string(cursor).encode("utf-8")


def remove_escaped_whitespace_recursive(value):
    """Remove all escaped whitespace characters from given value.

    PostgreSQL supports constant escaped strings by appending an E' to each string that
    contains whitespace in them (amongst other characters). See:
    https://www.postgresql.org/docs/current/sql-syntax-lexical.html#SQL-SYNTAX-STRINGS-ESCAPE

    However, Redshift does not support this syntax. So, to avoid any escaping by
    underlying PostgreSQL library, we remove the whitespace ourselves as defined in the
    translation table WHITESPACE_TRANSLATE.

    This function is recursive just to be extremely careful and catch any whitespace that
    may be sneaked in a dictionary key or sequence.
    """
    match value:
        case str(s):
            return " ".join(s.replace("\b", " ").split())

        case bytes(b):
            return remove_escaped_whitespace_recursive(b.decode("utf-8"))

        case [*sequence]:
            return type(value)(remove_escaped_whitespace_recursive(sequence_value) for sequence_value in sequence)

        case set(elements):
            return {remove_escaped_whitespace_recursive(element) for element in elements}

        case {**mapping}:
            return {k: remove_escaped_whitespace_recursive(v) for k, v in mapping.items()}

        case value:
            return value
