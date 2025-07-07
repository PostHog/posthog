import asyncio
import collections
import collections.abc
import concurrent.futures
import contextlib
import gzip
import io
import json
import typing

import brotli
import orjson
import pyarrow as pa
import pyarrow.parquet as pq
import structlog
from django.conf import settings

from posthog.temporal.batch_exports.metrics import ExecutionTimeRecorder

logger = structlog.get_logger()


class Chunk(typing.NamedTuple):
    """A chunk of bytes indicating if they are at the end of a file."""

    data: bytes
    is_eof: bool


class _TransformerProtocol(typing.Protocol):
    """Transformer protocol iterating record batches into chunks of bytes."""

    async def iter(
        self, record_batches: collections.abc.AsyncIterable[pa.RecordBatch], max_file_size_bytes: int = 0
    ) -> collections.abc.AsyncIterator[Chunk]:
        if typing.TYPE_CHECKING:
            # We need a yield for mypy to interpret this as Callable[[...], AsyncIterator[int]].
            # Otherwise, it will treat it as Callable[[], Coroutine[Any, Any, AsyncIterator[int]]].
            # See: https://mypy.readthedocs.io/en/stable/more_types.html#asynchronous-iterators
            yield Chunk(b"", False)
        raise NotImplementedError


def get_stream_transformer(
    format: str, compression: str | None = None, schema: pa.Schema | None = None, include_inserted_at: bool = False
) -> _TransformerProtocol:
    match format.lower():
        case "jsonlines" if compression != "brotli":
            return JSONLStreamTransformer(compression=compression, include_inserted_at=include_inserted_at)
        case "jsonlines" if compression == "brotli":
            return JSONLBrotliStreamTransformer(include_inserted_at=include_inserted_at)
        case "parquet":
            if schema is None:
                raise ValueError("Schema is required for Parquet")
            return ParquetStreamTransformer(
                compression=compression, schema=schema, include_inserted_at=include_inserted_at
            )
        case _:
            raise ValueError(f"Unsupported format: {format}")


class JSONLStreamTransformer:
    """A transformer to convert record batches into lines of JSON.

    Each record in a record batch corresponds to one JSON line.
    """

    def __init__(
        self,
        compression: str | None = None,
        include_inserted_at: bool = False,
        max_workers: int = settings.BATCH_EXPORT_TRANSFORMER_MAX_WORKERS,
    ):
        self.include_inserted_at = include_inserted_at
        self.compression = compression
        self.max_workers = max_workers

        self._futures_pending: set[asyncio.Future[list[bytes]]] = set()
        self._semaphore = asyncio.Semaphore(max_workers)

    async def iter(
        self, record_batches: collections.abc.AsyncIterable[pa.RecordBatch], max_file_size_bytes: int = 0
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

        with concurrent.futures.ProcessPoolExecutor(max_workers=self.max_workers) as executor:
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

                            if max_file_size_bytes and current_file_size + len(chunk) > max_file_size_bytes:
                                yield Chunk(b"", True)
                                current_file_size = 0

                            else:
                                current_file_size += len(chunk)


class JSONLBrotliStreamTransformer:
    def __init__(
        self,
        include_inserted_at: bool = False,
        max_workers: int = settings.BATCH_EXPORT_TRANSFORMER_MAX_WORKERS,
    ):
        self.include_inserted_at = include_inserted_at
        self.max_workers = max_workers

        self._futures_pending: set[asyncio.Future[list[bytes]]] = set()
        self._semaphore = asyncio.Semaphore(max_workers)
        self._brotli_compressor = None

    async def iter(
        self, record_batches: collections.abc.AsyncIterable[pa.RecordBatch], max_file_size_bytes: int = 0
    ) -> collections.abc.AsyncIterator[Chunk]:
        """Distribute transformation of record batches into multiple processes.

        This supports brotli compression by compressing only in the main
        process. So, the brotli compressor keeps the necessary state to finalize
        every file.

        See `JSONLStreamTransformer` for an outline of the pipeline.
        """
        current_file_size = 0

        with concurrent.futures.ProcessPoolExecutor(max_workers=self.max_workers) as executor:
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
                            chunk = self._compress(chunk)
                            await asyncio.sleep(0)  # In case compressing took too long.

                            yield Chunk(chunk, False)

                            if max_file_size_bytes and current_file_size + len(chunk) > max_file_size_bytes:
                                data = await asyncio.to_thread(self._finish_brotli_compressor)

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
            self._brotli_compressor = brotli.Compressor()
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
        _ = column_names.pop(column_names.index("_inserted_at"))

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
                    dumped = orjson.dumps(d, default=str) + b"\n"

            else:
                # In this case, we fallback to the slower but more permissive stdlib
                # json.
                logger.exception("Orjson detected a deeply nested dict: %s", d)
                dumped = json.dumps(d, default=str).encode("utf-8") + b"\n"
        else:
            # Orjson is very strict about invalid unicode. This slow path protects us
            # against things we've observed in practice, like single surrogate codes, e.g.
            # "\ud83d"
            logger.exception("Failed to encode with orjson: %s", d)
            cleaned_content = replace_broken_unicode(d)
            dumped = orjson.dumps(cleaned_content, default=str) + b"\n"

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


def json_dumps_bytes(d) -> bytes:
    try:
        return orjson.dumps(d, default=str)
    except orjson.JSONEncodeError:
        # orjson is very strict about invalid unicode. This slow path protects us against
        # things we've observed in practice, like single surrogate codes, e.g. "\ud83d"
        logger.exception("Failed to encode with orjson: %s", d)
        cleaned_d = replace_broken_unicode(d)
        return orjson.dumps(cleaned_d, default=str)


class ParquetStreamTransformer:
    """A transformer to convert record batches into Parquet."""

    def __init__(
        self,
        schema: pa.Schema,
        compression: str | None = None,
        compression_level: int | None = None,
        include_inserted_at: bool = False,
    ):
        self.include_inserted_at = include_inserted_at
        self.schema = schema
        self.compression = compression
        self.compression_level = compression_level

        # For Parquet, we need to handle schema and batching
        self._parquet_writer: pq.ParquetWriter | None = None
        self._parquet_buffer = io.BytesIO()

    async def iter(
        self, record_batches: collections.abc.AsyncIterable[pa.RecordBatch], max_file_size_bytes: int = 0
    ) -> collections.abc.AsyncIterator[Chunk]:
        """Iterate over record batches transforming them into chunks."""
        current_file_size = 0

        async for record_batch in record_batches:
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

                if max_file_size_bytes and current_file_size + len(chunk) > max_file_size_bytes:
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

    def finish_parquet_file(self) -> bytes:
        """Ensure underlying Parquet writer is closed before flushing buffer."""
        self.parquet_writer.close()
        self._parquet_writer = None

        final_data = self._parquet_buffer.getvalue()

        self._parquet_buffer = io.BytesIO()

        return final_data

    def write_record_batch(self, record_batch: pa.RecordBatch) -> bytes:
        """Write record batch to buffer as Parquet."""
        column_names = self.parquet_writer.schema.names
        if not self.include_inserted_at:
            column_names.pop(column_names.index("_inserted_at"))

        self.parquet_writer.write_batch(record_batch.select(column_names))
        data = self._parquet_buffer.getvalue()

        self._parquet_buffer.seek(0)
        self._parquet_buffer.truncate(0)

        return data
