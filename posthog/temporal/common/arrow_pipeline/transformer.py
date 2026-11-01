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
import psycopg.adapt
import pyarrow.parquet as pq
import psycopg.types.array

from posthog.temporal.common.arrow_pipeline.table import Field, Table, TypeTupleToCastMapping, are_types_compatible
from posthog.temporal.common.arrow_pipeline.worker_init import init_worker
from posthog.temporal.common.logger import get_write_only_logger

logger = get_write_only_logger()

RecursionLimitHandler = collections.abc.Callable[[dict[str, typing.Any]], bool]
"""Try to make a record that hit orjson's recursion limit dumpable, by changing it in place.

Return `True` to dump the changed record with orjson again, or `False` to fall back to the
stdlib `json` module. Transformers send the handler to worker processes, so it must be a
module-level function that pickle can import.
"""


class TransformTimer(typing.Protocol):
    """Time one transform step, for example to record a metric.

    Transformers call the timer once per step and run the step inside the returned context
    manager. `log_message` is a printf-style message that can use `num_records`,
    `mb_processed`, `duration_seconds` and `mb_per_second`.
    """

    def __call__(
        self,
        name: str,
        /,
        *,
        description: str,
        log_message: str,
        num_records: int,
        num_bytes: int,
    ) -> contextlib.AbstractContextManager[object]: ...


def _time_transform(
    timer: TransformTimer | None,
    name: str,
    /,
    *,
    description: str,
    log_message: str,
    num_records: int,
    num_bytes: int,
) -> contextlib.AbstractContextManager[object]:
    if timer is None:
        return contextlib.nullcontext()
    return timer(name, description=description, log_message=log_message, num_records=num_records, num_bytes=num_bytes)


def _remove_fields(schema: pa.Schema, field_names: collections.abc.Iterable[str]) -> pa.Schema:
    """Return `schema` without the fields named `field_names`, ignoring names that it does not have."""
    for name in field_names:
        if (index := schema.get_field_index(name)) >= 0:
            schema = schema.remove(index)
    return schema


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
            # generic. So, the best we can do is to just cast.
            yield typing.cast(T, Chunk(b"", False))
        raise NotImplementedError


ChunkTransformerProtocol = TransformerProtocol[Chunk]


def get_json_stream_transformer(
    exclude_columns: collections.abc.Iterable[str] = (),
    compression: str | None = None,
    max_file_size_bytes: int = 0,
    max_workers: int = settings.BATCH_EXPORT_TRANSFORMER_MAX_WORKERS,
    on_recursion_limit: RecursionLimitHandler | None = None,
) -> ChunkTransformerProtocol:
    if compression == "brotli":
        return JSONLBrotliStreamTransformer(
            exclude_columns=exclude_columns,
            max_file_size_bytes=max_file_size_bytes,
            max_workers=max_workers,
            on_recursion_limit=on_recursion_limit,
        )

    return JSONLStreamTransformer(
        compression=compression,
        exclude_columns=exclude_columns,
        max_file_size_bytes=max_file_size_bytes,
        max_workers=max_workers,
        on_recursion_limit=on_recursion_limit,
    )


class JSONLStreamTransformer:
    """A transformer to convert record batches into lines of JSON.

    Each record in a record batch corresponds to one JSON line. Columns in `exclude_columns`
    are not written.
    """

    def __init__(
        self,
        compression: str | None = None,
        exclude_columns: collections.abc.Iterable[str] = (),
        max_file_size_bytes: int = 0,
        max_workers: int = settings.BATCH_EXPORT_TRANSFORMER_MAX_WORKERS,
        on_recursion_limit: RecursionLimitHandler | None = None,
    ):
        self.exclude_columns = frozenset(exclude_columns)
        self.on_recursion_limit = on_recursion_limit
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
            max_workers=self.max_workers,
            mp_context=mp.get_context("forkserver"),
            initializer=init_worker,
        ) as executor:
            async with _record_batches_producer(
                record_batches,
                executor=executor,
                semaphore=self._semaphore,
                futures_pending=self._futures_pending,
                exclude_columns=self.exclude_columns,
                on_recursion_limit=self.on_recursion_limit,
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
        exclude_columns: collections.abc.Iterable[str] = (),
        max_file_size_bytes: int = 0,
        max_workers: int = settings.BATCH_EXPORT_TRANSFORMER_MAX_WORKERS,
        on_recursion_limit: RecursionLimitHandler | None = None,
    ):
        self.exclude_columns = frozenset(exclude_columns)
        self.on_recursion_limit = on_recursion_limit
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
            max_workers=self.max_workers,
            mp_context=mp.get_context("forkserver"),
            initializer=init_worker,
        ) as executor:
            async with _record_batches_producer(
                record_batches,
                executor=executor,
                semaphore=self._semaphore,
                futures_pending=self._futures_pending,
                exclude_columns=self.exclude_columns,
                on_recursion_limit=self.on_recursion_limit,
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
    exclude_columns: frozenset[str],
    on_recursion_limit: RecursionLimitHandler | None,
    compression: str | None = None,
):
    """Manage a task to produce record batches to run in executor."""
    loop = asyncio.get_running_loop()

    async def producer():
        """Produce record batches to execute in process pool."""
        async for record_batch in record_batches:
            _ = await semaphore.acquire()

            future = loop.run_in_executor(
                executor, dump_record_batch, record_batch, compression, exclude_columns, on_recursion_limit
            )
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
    exclude_columns: collections.abc.Container[str] = (),
    on_recursion_limit: RecursionLimitHandler | None = None,
) -> list[bytes]:
    """Dump all records in a record batch to JSON lines, without the columns in `exclude_columns`."""
    column_names = [name for name in record_batch.column_names if name not in exclude_columns]

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
            compress(dump_dict(record_dict, on_recursion_limit))
            for record_dict in record_batch.select(column_names).to_pylist()
            if record_dict
        ]
    else:
        return [
            dump_dict(record_dict, on_recursion_limit)
            for record_dict in record_batch.select(column_names).to_pylist()
            if record_dict
        ]


def dump_dict(d: dict[str, typing.Any], on_recursion_limit: RecursionLimitHandler | None = None) -> bytes:
    """Dump a dictionary to a line of JSON.

    When orjson reaches its recursion limit, `on_recursion_limit` can change `d` so that orjson
    can dump it. See `RecursionLimitHandler`.
    """
    try:
        dumped = orjson.dumps(d, default=str) + b"\n"
    except orjson.JSONEncodeError as err:
        # NOTE: `orjson.JSONEncodeError` is actually just an alias for `TypeError`.
        # This handler will catch everything coming from orjson, so we have to
        # awkwardly check error messages.
        if str(err) == "Recursion limit reached":
            # Orjson enforces an unmodifiable recursion limit (256), so we can't
            # dump very nested dicts.
            if on_recursion_limit is not None and on_recursion_limit(d):
                dumped = dump_dict(d, on_recursion_limit)

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
            dumped = dump_dict(cleaned_content, on_recursion_limit)

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


def get_parquet_column_paths(schema: pa.Schema, field_names: collections.abc.Iterable[str]) -> list[str]:
    """Return the Parquet leaf column paths of the fields named `field_names` in `schema`.

    `ParquetWriter` matches `use_dictionary` and `write_statistics` against leaf column paths, such as
    `tags.list.element` for a list field, not against top-level field names.
    """
    buffer = io.BytesIO()
    pq.write_table(pa.schema([schema.field(name) for name in field_names]).empty_table(), buffer)
    parquet_schema = pq.ParquetFile(buffer).schema
    return [parquet_schema.column(index).path for index in range(len(parquet_schema))]


class ParquetStreamTransformer:
    """A transformer to convert record batches into Parquet.

    Record batches are held until `max_buffered_arrow_bytes` of them are pending, then written as one
    row group. The limit counts Arrow bytes, so the row group in the file is usually smaller.

    Columns in `exclude_columns` are not written. Columns in `json_columns` hold JSON documents, so
    they get no dictionary encoding and no statistics.
    """

    # Close a file when less than this fraction of its max size is left. Otherwise, the last row
    # group ends up being very small and we're also more likely to go over the max file size.
    MIN_REMAINING_FILE_SIZE_FRACTION = 0.05

    def __init__(
        self,
        compression: str | None = None,
        compression_level: int | None = None,
        exclude_columns: collections.abc.Iterable[str] = (),
        max_file_size_bytes: int = 0,
        max_buffered_arrow_bytes: int | None = None,
        json_columns: collections.abc.Iterable[str] = (),
        transform_timer: TransformTimer | None = None,
    ):
        self.exclude_columns = frozenset(exclude_columns)
        self.json_columns = frozenset(json_columns)
        self.compression = compression
        self.compression_level = compression_level
        self.max_file_size_bytes = max_file_size_bytes
        self.transform_timer = transform_timer

        if max_buffered_arrow_bytes is None:
            max_buffered_arrow_bytes = settings.BATCH_EXPORT_PARQUET_MAX_BUFFERED_ARROW_BYTES
        if max_file_size_bytes:
            max_buffered_arrow_bytes = min(max_buffered_arrow_bytes, max_file_size_bytes)
        self.max_buffered_arrow_bytes = max_buffered_arrow_bytes

        self._parquet_writer: pq.ParquetWriter | None = None
        self._parquet_buffer = io.BytesIO()
        self._schema: pa.Schema | None = None
        self._pending_record_batches: list[pa.RecordBatch] = []
        self._pending_record_batches_bytes = 0
        self._pending_record_batches_rows = 0
        self._non_json_column_paths: list[str] = []
        self._current_file_size = 0
        # The compression ratio (Parquet bytes written per Arrow byte) achieved when writing the
        # previous row group. We use this as an estimate for calculating how many bytes will be
        # written next time. It starts at 1 because Parquet output is usually no larger than its
        # Arrow input.
        self._compression_ratio = 1.0

    async def iter(
        self, record_batches: collections.abc.AsyncIterable[pa.RecordBatch]
    ) -> collections.abc.AsyncIterator[Chunk]:
        """Iterate over record batches transforming them into chunks."""
        async for record_batch in record_batches:
            self.schema = record_batch.schema
            self._add_pending_record_batch(record_batch)

            if not self._is_row_group_ready():
                continue

            with _time_transform(
                self.transform_timer,
                "parquet_stream_transformer_record_batch_transform_duration",
                description="Duration to write pending record batches as a Parquet row group.",
                log_message=(
                    "Wrote row group with %(num_records)d records to parquet."
                    " Record batches size: %(mb_processed).2f MB, process time:"
                    " %(duration_seconds)d seconds, speed: %(mb_per_second).2f MB/s"
                ),
                num_records=self._pending_record_batches_rows,
                num_bytes=self._pending_record_batches_bytes,
            ):
                # Running write in a thread to yield control back to event loop.
                chunk = await asyncio.to_thread(self._flush_row_group)

            yield Chunk(chunk, False)
            self._current_file_size += len(chunk)

            if self._is_current_file_full():
                footer = await asyncio.to_thread(self._finish_parquet_file)

                yield Chunk(footer, True)

        # Nothing is left to finish when no record batches arrived, or when the last file was finished in the loop.
        if self._current_file_size == 0 and not self._pending_record_batches:
            return

        footer = await asyncio.to_thread(self._finish_parquet_file)
        yield Chunk(footer, True)

    def _get_parquet_writer(self) -> pq.ParquetWriter:
        if self._parquet_writer is None:
            self._parquet_writer = pq.ParquetWriter(
                self._parquet_buffer,
                schema=self.schema,
                compression="none" if self.compression is None else self.compression,  # type: ignore
                compression_level=self.compression_level,
                use_dictionary=self._non_json_column_paths,  # type: ignore
                # Min/max statistics on JSON strings cannot help a reader skip row groups, so we do
                # not write statistics for them to save on file size.
                write_statistics=self._non_json_column_paths,
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
        if self._schema is not None:
            return

        schema = _remove_fields(schema, self.exclude_columns)

        self._schema = schema
        self._non_json_column_paths = get_parquet_column_paths(
            schema, [name for name in schema.names if name not in self.json_columns]
        )

    def _finish_parquet_file(self) -> bytes:
        """Write any pending row group, close the file, and return the rest of its bytes."""
        self._write_pending_row_group()
        self._get_parquet_writer().close()
        self._parquet_writer = None
        self._current_file_size = 0

        return self._drain_parquet_buffer()

    def _is_current_file_full(self) -> bool:
        """Return whether the current file has too little space left for another row group."""
        if not self.max_file_size_bytes:
            return False

        remaining_bytes = self.max_file_size_bytes - self._current_file_size
        return remaining_bytes < self.max_file_size_bytes * self.MIN_REMAINING_FILE_SIZE_FRACTION

    def _is_row_group_ready(self) -> bool:
        """Return whether enough record batches are pending to write a row group."""
        if not self.max_file_size_bytes:
            return self._pending_record_batches_bytes >= self.max_buffered_arrow_bytes

        # Near the end of a file, the limit is the space left in the file converted to Arrow bytes
        # using our compression ratio estimate.
        remaining_bytes = self.max_file_size_bytes - self._current_file_size
        limit_bytes = min(self.max_buffered_arrow_bytes, remaining_bytes / self._compression_ratio)
        return self._pending_record_batches_bytes >= limit_bytes

    def _add_pending_record_batch(self, record_batch: pa.RecordBatch) -> None:
        """Hold a record batch until enough record batches are pending to write a row group."""
        record_batch = record_batch.select(self.schema.names)
        self._pending_record_batches.append(record_batch)
        self._pending_record_batches_bytes += record_batch.nbytes
        self._pending_record_batches_rows += record_batch.num_rows

    def _flush_row_group(self) -> bytes:
        """Write all pending record batches as one row group, and return the bytes written."""
        pending_record_batches_bytes = self._pending_record_batches_bytes
        self._write_pending_row_group()
        data = self._drain_parquet_buffer()

        if pending_record_batches_bytes:
            self._compression_ratio = len(data) / pending_record_batches_bytes

        return data

    def _drain_parquet_buffer(self) -> bytes:
        """Return the bytes in the buffer, and empty it for the next write."""
        data = self._parquet_buffer.getvalue()
        self._parquet_buffer.seek(0)
        self._parquet_buffer.truncate(0)
        return data

    def _write_pending_row_group(self) -> None:
        """Write all pending record batches to buffer as a single Parquet row group."""
        if not self._pending_record_batches:
            return

        table = pa.Table.from_batches(self._pending_record_batches, schema=self.schema)
        self._get_parquet_writer().write_table(table, row_group_size=max(table.num_rows, 1))

        self._pending_record_batches = []
        self._pending_record_batches_bytes = 0
        self._pending_record_batches_rows = 0


def _ensure_curly_brackets_array(v: list[typing.Any]) -> str:
    """Convert list to PostgreSQL array literal format with proper escaping.

    Supports nested arrays and properly escapes special characters.
    Uses psycopg3's ListDumper for correct PostgreSQL array formatting.
    """

    tx = psycopg.adapt.Transformer()
    dumper = psycopg.types.array.ListDumper(list, tx)
    result = dumper.dump(v)
    assert result is not None
    # Result can be bytes or memoryview, convert to string
    if isinstance(result, memoryview):
        result = bytes(result)
    return result.decode("utf-8")


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
        exclude_columns: collections.abc.Iterable[str] = (),
        max_file_size_bytes: int = 0,
    ):
        self.field_names = field_names
        self.delimiter = delimiter
        self.quote_char = quote_char
        self.escape_char = escape_char
        self.line_terminator = line_terminator
        self.quoting = quoting
        self.exclude_columns = frozenset(exclude_columns)
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

        column_names = [name for name in self.field_names if name not in self.exclude_columns]

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
            rows.append({k: _ensure_curly_brackets_array(v) if isinstance(v, list) else v for k, v in record.items()})

        writer.writerows(rows)
        text_wrapper.flush()

        return buffer.getvalue()


def serialize(record_batch: pa.RecordBatch, column_names: list[str]) -> bytes:
    return record_batch.select(column_names).serialize().to_pybytes()


class SerializedStreamTransformer:
    """A transformer to serialize record batches into Arrow IPC format."""

    def __init__(
        self,
        pool: concurrent.futures.ProcessPoolExecutor,
        exclude_columns: collections.abc.Iterable[str] = (),
        max_file_size_bytes: int = 0,
        transform_timer: TransformTimer | None = None,
    ):
        self.pool = pool
        self.exclude_columns = frozenset(exclude_columns)
        self.max_file_size_bytes = max_file_size_bytes
        self.transform_timer = transform_timer

        self._schema: pa.Schema | None = None

    async def iter(
        self, record_batches: collections.abc.AsyncIterable[pa.RecordBatch]
    ) -> collections.abc.AsyncIterator[Chunk]:
        """Iterate over record batches transforming them into chunks."""
        current_file_size = 0
        loop = asyncio.get_running_loop()

        async for record_batch in record_batches:
            self.schema = record_batch.schema

            with _time_transform(
                self.transform_timer,
                "serialized_transformer_record_batch_transform_duration",
                description="Duration to serialize a record batch.",
                log_message=(
                    "Serialized record batch with %(num_records)d records."
                    " Record batch size: %(mb_processed).2f MB, process time:"
                    " %(duration_seconds)d seconds, speed: %(mb_per_second).2f MB/s"
                ),
                num_records=record_batch.num_rows,
                num_bytes=record_batch.nbytes,
            ):
                chunk = await loop.run_in_executor(self.pool, serialize, record_batch, self.schema.names)
                yield Chunk(chunk, False)

                if self.max_file_size_bytes and current_file_size + len(chunk) > self.max_file_size_bytes:
                    yield Chunk(b"", True)
                    current_file_size = 0

                else:
                    current_file_size += len(chunk)

        yield Chunk(b"", True)

    @property
    def schema(self) -> pa.Schema:
        if not self._schema:
            raise ValueError("Schema not set, is the transformer running?")
        return self._schema

    @schema.setter
    def schema(self, schema: pa.Schema) -> None:
        if self._schema is not None:
            return

        self._schema = _remove_fields(schema, self.exclude_columns)


class IncompatibleTypesError(TypeError):
    """Exception for incompatible types between source and destination.

    We subclass `TypeError` as Temporal matches on exception name to decide whether to
    retry or not. With a subclass this means we can decide whether this particular error
    is retryable or not while allowing callers to still handle it with
    `except TypeError`.
    """

    def __init__(self, field: Field, array_type: pa.DataType):
        super().__init__(
            f"'{field.name}' has incoming type '{array_type}' which is not compatible with destination field's type: '{field.data_type}'"
        )


class SchemaTransformer:
    """Transformer to cast record batches into a new schema."""

    def __init__(
        self,
        table: Table,
        extra_compatible_types: TypeTupleToCastMapping | None = None,
        raise_on_incompatible: bool = False,
    ):
        self.table = table
        self.extra_compatible_types = extra_compatible_types
        self.raise_on_incompatible = raise_on_incompatible

    async def iter(
        self,
        record_batches: collections.abc.AsyncIterable[pa.RecordBatch],
    ) -> collections.abc.AsyncIterator[pa.RecordBatch]:
        async for record_batch in record_batches:
            yield self.cast_record_batch(record_batch)

    def cast_record_batch(self, record_batch: pa.RecordBatch) -> pa.RecordBatch:
        """Cast a record batch into a new schema that matches `self.table`.

        If the record batch's schema already matches table, then nothing is cast. If a
        particular field cannot be cast to the corresponding target field type, then an
        exception is raised when `self.raise_on_incompatible` is `True`, otherwise we
        optimistically assume the destination can handle the inconsistency.
        """
        field_names = record_batch.schema.names

        arrays = []
        new_field_names = []
        for field_name, array in zip(field_names, record_batch.select(field_names).itercolumns()):
            try:
                field = self.table[field_name]
            except KeyError:
                logger.warning(
                    "Field missing in target",
                    name=field_name,
                    table=self.table.fully_qualified_name,
                )
                continue

            if field.name != field_name:
                logger.warning(
                    "Field aliased",
                    field=field.name,
                    alias=field.alias,
                    table=self.table.fully_qualified_name,
                )
            new_field_names.append(field.name)

            if array.type == field.data_type:
                arrays.append(array)
                continue

            compatible, cast = are_types_compatible(array.type, field.data_type, self.extra_compatible_types)

            if compatible:
                assert cast is not None, "If types are compatible cast function should be defined"
                arrays.append(cast(array))
            else:
                if self.raise_on_incompatible:
                    raise IncompatibleTypesError(field, array.type)

                logger.warning(
                    "Detected incompatible types",
                    field=field.name,
                    source_type=array.type,
                    field_type=field.data_type,
                    table=self.table.fully_qualified_name,
                )
                arrays.append(array)

        return pa.RecordBatch.from_arrays(
            arrays,
            names=new_field_names,
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

        pipeline: collections.abc.AsyncIterable[Chunk] = functools.reduce(  # ty: ignore[invalid-assignment]
            generate,
            iter(self.transformers),
            record_batches,  # type: ignore[arg-type]
        )

        async for chunk in pipeline:
            yield chunk
