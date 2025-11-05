import io
import csv
import gzip
import json
import typing
import asyncio
import functools
import contextlib
import collections
import collections.abc
import multiprocessing as mp
import concurrent.futures

from django.conf import settings

import brotli
import orjson
import pyarrow as pa
import pyarrow.parquet as pq
from psycopg import sql

from posthog.temporal.common.logger import get_write_only_logger

from products.batch_exports.backend.temporal.metrics import ExecutionTimeRecorder
from products.batch_exports.backend.temporal.pipeline.table import Table, TypeTupleToCastMapping, are_types_compatible

logger = get_write_only_logger()


class Chunk(typing.NamedTuple):
    """A chunk of bytes indicating if they are at the end of a file."""

    data: bytes
    is_eof: bool


class TransformerProtocol[T](typing.Protocol):
    """Transformer protocol iterating record batches into chunks of bytes."""

    async def iter(
        self, record_batches: collections.abc.AsyncIterable[pa.RecordBatch]
    ) -> collections.abc.AsyncIterator[T]:
        if typing.TYPE_CHECKING:
            # We need a yield for mypy to interpret this as Callable[[...], AsyncIterator[int]].
            # Otherwise, it will treat it as Callable[[], Coroutine[Any, Any, AsyncIterator[int]]].
            # See: https://mypy.readthedocs.io/en/stable/more_types.html#asynchronous-iterators
            # Update: Unfortunately, now that the protocol is generic, we cannot yield a
            # Chunk as that is a concrete type. But we still need the yield for the
            # reason above. And if we have a yield, then we must yield something that
            # fits the type hint for mypy to be happy. But no concrete type fits a
            # generic. So, the best we can do is to just ignore.
            yield Chunk(b"", False)  # type: ignore[misc]
        raise NotImplementedError


ChunkTransformerProtocol = TransformerProtocol[Chunk]


def get_json_stream_transformer(
    include_inserted_at: bool = False,
    compression: str | None = None,
    max_file_size_bytes: int = 0,
    max_workers: int = settings.BATCH_EXPORT_TRANSFORMER_MAX_WORKERS,
) -> ChunkTransformerProtocol:
    if compression == "brotli":
        return JSONLBrotliStreamTransformer(
            include_inserted_at=include_inserted_at, max_file_size_bytes=max_file_size_bytes, max_workers=max_workers
        )

    return JSONLStreamTransformer(
        compression=compression,
        include_inserted_at=include_inserted_at,
        max_file_size_bytes=max_file_size_bytes,
        max_workers=max_workers,
    )


class JSONLStreamTransformer:
    """A transformer to convert record batches into lines of JSON.

    Each record in a record batch corresponds to one JSON line.
    """

    def __init__(
        self,
        compression: str | None = None,
        include_inserted_at: bool = False,
        max_file_size_bytes: int = 0,
        max_workers: int = settings.BATCH_EXPORT_TRANSFORMER_MAX_WORKERS,
    ):
        self.include_inserted_at = include_inserted_at
        self.compression = compression
        self.max_workers = max_workers
        self.max_file_size_bytes = max_file_size_bytes

        self._futures_pending: set[asyncio.Future[list[bytes]]] = set()
        self._semaphore = asyncio.Semaphore(max_workers)

    async def iter(
        self, record_batches: collections.abc.AsyncIterable[pa.RecordBatch]
    ) -> collections.abc.AsyncIterator[Chunk]:
        """Distribute transformation of record batches into multiple processes.

        The multiprocess pipeline works as follows:
        1. Start a `ProcessPoolExecutor` with a number of workers to distribute
           the workload.
        2. Spawn a producer asyncio task to iterate through record batches,
           and spawn multiprocessing tasks for the workers.
        3. We use a `asyncio.Semaphore` to block the producer loop to avoid
           spawning up too many multiprocessing tasks at a time.
        4. The consumer main thread waits on futures as they are done, and
           iterates through chunks.
        """
        current_file_size = 0

        with concurrent.futures.ProcessPoolExecutor(
            max_workers=self.max_workers, mp_context=mp.get_context("fork")
        ) as executor:
            async with _record_batches_producer(
                record_batches,
                executor=executor,
                semaphore=self._semaphore,
                futures_pending=self._futures_pending,
                include_inserted_at=self.include_inserted_at,
                compression=self.compression,
            ) as producer_task:
                while True:
                    try:
                        done, _ = await asyncio.wait(self._futures_pending, return_when=asyncio.FIRST_COMPLETED)
                    except ValueError:
                        if producer_task.done():
                            break

                        await asyncio.sleep(0)
                        continue

                    for future in done:
                        chunks = await future
                        self._semaphore.release()
                        self._futures_pending.remove(future)

                        for chunk in chunks:
                            yield Chunk(chunk, False)

                            if self.max_file_size_bytes and current_file_size + len(chunk) > self.max_file_size_bytes:
                                yield Chunk(b"", True)
                                current_file_size = 0

                            else:
                                current_file_size += len(chunk)


class JSONLBrotliStreamTransformer:
    def __init__(
        self,
        include_inserted_at: bool = False,
        max_file_size_bytes: int = 0,
        max_workers: int = settings.BATCH_EXPORT_TRANSFORMER_MAX_WORKERS,
    ):
        self.include_inserted_at = include_inserted_at
        self.max_file_size_bytes = max_file_size_bytes
        self.max_workers = max_workers

        self._futures_pending: set[asyncio.Future[list[bytes]]] = set()
        self._semaphore = asyncio.Semaphore(max_workers)
        self._brotli_compressor = None

    async def iter(
        self, record_batches: collections.abc.AsyncIterable[pa.RecordBatch]
    ) -> collections.abc.AsyncIterator[Chunk]:
        """Distribute transformation of record batches into multiple processes.

        This supports brotli compression by compressing only in the main
        process. So, the brotli compressor keeps the necessary state to finalize
        every file.

        See `JSONLStreamTransformer` for an outline of the pipeline.
        """
        loop = asyncio.get_running_loop()

        current_file_size = 0

        with concurrent.futures.ProcessPoolExecutor(
            max_workers=self.max_workers, mp_context=mp.get_context("fork")
        ) as executor:
            async with _record_batches_producer(
                record_batches,
                executor=executor,
                semaphore=self._semaphore,
                futures_pending=self._futures_pending,
                include_inserted_at=self.include_inserted_at,
                compression=None,
            ) as producer_task:
                while True:
                    try:
                        done, _ = await asyncio.wait(self._futures_pending, return_when=asyncio.FIRST_COMPLETED)
                    except ValueError:
                        if producer_task.done():
                            break

                        await asyncio.sleep(0)
                        continue

                    for future in done:
                        chunks = await future
                        self._semaphore.release()
                        self._futures_pending.remove(future)

                        for chunk in chunks:
                            chunk = await loop.run_in_executor(None, self._compress, chunk)

                            yield Chunk(chunk, False)

                            if self.max_file_size_bytes and current_file_size + len(chunk) > self.max_file_size_bytes:
                                data = await loop.run_in_executor(None, self._finish_brotli_compressor)

                                yield Chunk(data, True)
                                current_file_size = 0

                            else:
                                current_file_size += len(chunk)

        data = self._finish_brotli_compressor()
        await asyncio.sleep(0)
        yield Chunk(data, True)

    def _compress(self, content: bytes | str) -> bytes:
        """Compress using brotli."""
        if isinstance(content, str):
            encoded = content.encode("utf-8")
        else:
            encoded = content

        self.brotli_compressor.process(encoded)
        return self.brotli_compressor.flush()

    def _finish_brotli_compressor(self) -> bytes:
        """Flush remaining brotli bytes."""
        bytes = self.brotli_compressor.finish()
        self._brotli_compressor = None
        return bytes

    @property
    def brotli_compressor(self) -> brotli._brotli.Compressor:
        if self._brotli_compressor is None:
            # Quality goes from 0 to 11.
            # Default is 11, aka maximum compression and worst performance.
            self._brotli_compressor = brotli.Compressor(quality=5)
        return self._brotli_compressor


@contextlib.asynccontextmanager
async def _record_batches_producer(
    record_batches: collections.abc.AsyncIterable[pa.RecordBatch],
    executor: concurrent.futures.ProcessPoolExecutor,
    semaphore: asyncio.Semaphore,
    futures_pending: set[asyncio.Future[list[bytes]]],
    include_inserted_at: bool,
    compression: str | None = None,
):
    """Manage a task to produce record batches to run in executor."""
    loop = asyncio.get_running_loop()

    async def producer():
        """Produce record batches to execute in process pool."""
        async for record_batch in record_batches:
            _ = await semaphore.acquire()

            future = loop.run_in_executor(executor, dump_record_batch, record_batch, compression, include_inserted_at)
            futures_pending.add(future)

    producer_task = asyncio.create_task(producer())

    try:
        yield producer_task
    finally:
        if not producer_task.done():
            _ = producer_task.cancel()

        try:
            await producer_task
        except asyncio.CancelledError:
            pass


def dump_record_batch(
    record_batch: pa.RecordBatch,
    compression: str | None,
    include_inserted_at: bool = False,
) -> list[bytes]:
    """Dump all records in a record batch to JSON lines."""
    column_names = record_batch.column_names
    if not include_inserted_at:
        try:
            _ = column_names.pop(column_names.index("_inserted_at"))
        except ValueError:
            # Already not included, filtered upstream.
            pass

    def compress(content: bytes):
        match compression:
            case "gzip":
                return gzip.compress(content)
            case None:
                return content
            case _:
                raise ValueError(f"Unsupported compression: '{compression}'")

    if compression:
        return [
            compress(dump_dict(record_dict))
            for record_dict in record_batch.select(column_names).to_pylist()
            if record_dict
        ]
    else:
        return [dump_dict(record_dict) for record_dict in record_batch.select(column_names).to_pylist() if record_dict]


def dump_dict(d: dict[str, typing.Any]) -> bytes:
    """Dump a dictionary to a line of JSON."""
    try:
        dumped = orjson.dumps(d, default=str) + b"\n"
    except orjson.JSONEncodeError as err:
        # NOTE: `orjson.JSONEncodeError` is actually just an alias for `TypeError`.
        # This handler will catch everything coming from orjson, so we have to
        # awkwardly check error messages.
        if str(err) == "Recursion limit reached":
            # Orjson enforces an unmodifiable recursion limit (256), so we can't
            # dump very nested dicts.
            if d.get("event", None) == "$web_vitals":
                # These are PostHog events that for a while included a bunch of
                # nested DOM structures. Eventually, this was removed, but these
                # events could still be present in database.
                # Let's try to clear the key with nested elements first.
                try:
                    del d["properties"]["$web_vitals_INP_event"]["attribution"]["interactionTargetElement"]
                except KeyError:
                    # We tried, fallback to the slower but more permissive stdlib
                    # json.
                    logger.exception("PostHog $web_vitals event didn't match expected structure")
                    dumped = json.dumps(d, default=str).encode("utf-8") + b"\n"
                else:
                    dumped = dump_dict(d)

            else:
                # In this case, we fallback to the slower but more permissive stdlib
                # json.
                logger.exception("Orjson detected a deeply nested dict")
                dumped = json.dumps(d, default=str).encode("utf-8") + b"\n"
        elif str(err) == "Integer exceeds 64-bit range":
            logger.warning("Failed to encode with orjson: Integer exceeds 64-bit range: %s", d)
            # Orjson doesn't support integers exceeding 64-bit range, so we fall back to json.dumps
            # see https://github.com/ijl/orjson/issues/301
            dumped = json.dumps(d, default=str).encode("utf-8") + b"\n"
        else:
            # Orjson is very strict about invalid unicode. This slow path protects us
            # against things we've observed in practice, like single surrogate codes, e.g.
            # "\ud83d"
            logger.exception("Failed to encode with orjson: %s", d)
            cleaned_content = replace_broken_unicode(d)
            dumped = dump_dict(cleaned_content)

    return dumped


def replace_broken_unicode(obj):
    if isinstance(obj, str):
        return obj.encode("utf-8", "replace").decode("utf-8")
    elif isinstance(obj, list):
        return [replace_broken_unicode(item) for item in obj]
    elif isinstance(obj, dict):
        return {replace_broken_unicode(key): replace_broken_unicode(value) for key, value in obj.items()}
    else:
        return obj


class ParquetStreamTransformer:
    """A transformer to convert record batches into Parquet."""

    def __init__(
        self,
        compression: str | None = None,
        compression_level: int | None = None,
        include_inserted_at: bool = False,
        max_file_size_bytes: int = 0,
    ):
        self.include_inserted_at = include_inserted_at
        self.compression = compression
        self.compression_level = compression_level
        self.max_file_size_bytes = max_file_size_bytes

        # For Parquet, we need to handle schema and batching
        self._parquet_writer: pq.ParquetWriter | None = None
        self._parquet_buffer = io.BytesIO()
        self._schema: pa.Schema | None = None

    async def iter(
        self, record_batches: collections.abc.AsyncIterable[pa.RecordBatch]
    ) -> collections.abc.AsyncIterator[Chunk]:
        """Iterate over record batches transforming them into chunks."""
        current_file_size = 0

        async for record_batch in record_batches:
            self.schema = record_batch.schema

            with ExecutionTimeRecorder(
                "parquet_stream_transformer_record_batch_transform_duration",
                description="Duration to transform a record batch into Parquet bytes.",
                log_message=(
                    "Processed record batch with %(num_records)d records to parquet."
                    " Record batch size: %(mb_processed).2f MB, process time:"
                    " %(duration_seconds)d seconds, speed: %(mb_per_second).2f MB/s"
                ),
                log_attributes={"num_records": record_batch.num_rows},
            ) as recorder:
                recorder.add_bytes_processed(record_batch.nbytes)
                # Running write in a thread to yield control back to event loop.
                chunk = await asyncio.to_thread(self.write_record_batch, record_batch)

                yield Chunk(chunk, False)

                if self.max_file_size_bytes and current_file_size + len(chunk) > self.max_file_size_bytes:
                    footer = await asyncio.to_thread(self.finish_parquet_file)

                    yield Chunk(footer, True)
                    current_file_size = 0

                else:
                    current_file_size += len(chunk)

        footer = await asyncio.to_thread(self.finish_parquet_file)
        yield Chunk(footer, True)

    @property
    def parquet_writer(self) -> pq.ParquetWriter:
        if self._parquet_writer is None:
            self._parquet_writer = pq.ParquetWriter(
                self._parquet_buffer,
                schema=self.schema,
                compression="none" if self.compression is None else self.compression,  # type: ignore
                compression_level=self.compression_level,
            )
        assert self._parquet_writer is not None
        return self._parquet_writer

    @property
    def schema(self) -> pa.Schema:
        if not self._schema:
            raise ValueError("Schema not set, is the transformer running?")
        return self._schema

    @schema.setter
    def schema(self, schema: pa.Schema) -> None:
        if self._schema:
            return

        if not self.include_inserted_at:
            if (index := schema.get_field_index("_inserted_at")) >= 0:
                schema = schema.remove(index)

        self._schema = schema

    def finish_parquet_file(self) -> bytes:
        """Ensure underlying Parquet writer is closed before flushing buffer."""
        self.parquet_writer.close()
        self._parquet_writer = None

        final_data = self._parquet_buffer.getvalue()

        self._parquet_buffer = io.BytesIO()

        return final_data

    def write_record_batch(self, record_batch: pa.RecordBatch) -> bytes:
        """Write record batch to buffer as Parquet."""
        column_names = self.schema.names
        self.parquet_writer.write_batch(record_batch.select(column_names))
        data = self._parquet_buffer.getvalue()

        self._parquet_buffer.seek(0)
        self._parquet_buffer.truncate(0)

        return data


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


def ensure_curly_brackets_array(v: list[typing.Any]) -> str:
    """Convert list to str and replace ends with curly braces for PostgreSQL arrays.

    NOTE: This doesn't support nested arrays (i.e. multi-dimensional arrays).
    """
    str_list = str(v)
    return f"{{{str_list[1:len(str_list)-1]}}}"


class CSVStreamTransformer:
    """A transformer to convert record batches into CSV/TSV format.

    TODO: Do we need to support compression and use ProcessPoolExecutor?
    """

    def __init__(
        self,
        field_names: collections.abc.Sequence[str],
        delimiter: str = ",",
        quote_char: str = '"',
        escape_char: str | None = "\\",
        line_terminator: str = "\n",
        quoting: typing.Literal[0, 1, 2, 3, 4, 5] = csv.QUOTE_NONE,
        include_inserted_at: bool = False,
        max_file_size_bytes: int = 0,
    ):
        self.field_names = field_names
        self.delimiter = delimiter
        self.quote_char = quote_char
        self.escape_char = escape_char
        self.line_terminator = line_terminator
        self.quoting = quoting
        self.include_inserted_at = include_inserted_at
        self.max_file_size_bytes = max_file_size_bytes

    async def iter(
        self,
        record_batches: collections.abc.AsyncIterable[pa.RecordBatch],
    ) -> collections.abc.AsyncIterator[Chunk]:
        """Iterate over record batches transforming them into CSV chunks."""
        current_file_size = 0

        async for record_batch in record_batches:
            chunk = await asyncio.to_thread(self.write_record_batch, record_batch)

            yield Chunk(chunk, False)

            if self.max_file_size_bytes and current_file_size + len(chunk) > self.max_file_size_bytes:
                yield Chunk(b"", True)
                current_file_size = 0

            else:
                current_file_size += len(chunk)

        yield Chunk(b"", True)

    def write_record_batch(self, record_batch: pa.RecordBatch) -> bytes:
        """Write record batch to CSV bytes."""

        column_names = list(self.field_names)
        if not self.include_inserted_at and "_inserted_at" in column_names:
            column_names.pop(column_names.index("_inserted_at"))

        buffer = io.BytesIO()
        text_wrapper = io.TextIOWrapper(buffer, encoding="utf-8", newline="")

        writer = csv.DictWriter(
            text_wrapper,
            fieldnames=column_names,
            extrasaction="ignore",
            delimiter=self.delimiter,
            quotechar=self.quote_char,
            escapechar=self.escape_char,
            quoting=self.quoting,
            lineterminator=self.line_terminator,
        )

        rows = []
        for record in record_batch.select(column_names).to_pylist():
            rows.append({k: ensure_curly_brackets_array(v) if isinstance(v, list) else v for k, v in record.items()})

        writer.writerows(rows)
        text_wrapper.flush()

        return buffer.getvalue()


class SchemaTransformer:
    """Transformer to cast record batches into a new schema."""

    def __init__(
        self,
        table: Table,
        extra_compatible_types: TypeTupleToCastMapping | None = None,
    ):
        self.table = table
        self.extra_compatible_types = extra_compatible_types

    async def iter(
        self,
        record_batches: collections.abc.AsyncIterable[pa.RecordBatch],
    ) -> collections.abc.AsyncIterator[pa.RecordBatch]:
        async for record_batch in record_batches:
            yield self.cast_record_batch(record_batch)

    def cast_record_batch(self, record_batch: pa.RecordBatch) -> pa.RecordBatch:
        """Cast a record batch into a new schema that matches `self.table`.

        If the record batch's schema already matches table, then nothing is cast.
        """
        field_names = [field.name for field in self.table.fields]

        arrays = []
        for field_name, array in zip(field_names, record_batch.select(field_names).itercolumns()):
            field = self.table[field_name]

            if array.type == field.data_type:
                arrays.append(array)
                continue

            compatible, cast = are_types_compatible(array.type, field.data_type, self.extra_compatible_types)

            if compatible:
                assert cast is not None, "If types are compatible cast function should be defined"

                arrays.append(cast(array))
            else:
                raise TypeError(
                    f"'{field_name}' has type '{array.type}' which is not compatible with field's type: '{field.data_type}'"
                )

        return pa.RecordBatch.from_arrays(
            arrays,
            names=field_names,
        )


class PipelineTransformer:
    """Transformer that pipes multiple transformers together.

    It is expected that the 1..n-1 transformers will yield record batches, and the n
    transformer will yield a `Chunk`. Thus, the pipeline in its entirety is a
    `ChunkTransformerProtocol`.

    Unfortunately, we don't really have a way to enforce this.
    """

    def __init__(self, transformers: collections.abc.Sequence[TransformerProtocol]):
        self.transformers = transformers

    async def iter(
        self, record_batches: collections.abc.AsyncIterable[pa.RecordBatch]
    ) -> collections.abc.AsyncIterator[Chunk]:
        async def generate(record_batches_iter, transformer):
            async for chunk in transformer.iter(record_batches_iter):
                yield chunk

        pipeline = functools.reduce(generate, iter(self.transformers), record_batches)

        async for chunk in pipeline:
            yield chunk  # type: ignore[misc]
