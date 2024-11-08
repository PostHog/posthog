"""This module contains a temporary file to stage data in batch exports."""

import abc
import asyncio
import collections.abc
import contextlib
import csv
import datetime as dt
import gzip
import json
import tempfile
import typing

import brotli
import orjson
import pyarrow as pa
import pyarrow.parquet as pq
import structlog

from posthog.temporal.common.utils import DateRange

logger = structlog.get_logger()


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


class BatchExportTemporaryFile:
    """A TemporaryFile used to as an intermediate step while exporting data.

    This class does not implement the file-like interface but rather passes any calls
    to the underlying tempfile.NamedTemporaryFile. We do override 'write' methods
    to allow tracking bytes and records.
    """

    def __init__(
        self,
        mode: str = "w+b",
        buffering=-1,
        compression: str | None = None,
        encoding: str | None = None,
        newline: str | None = None,
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | None = None,
        *,
        errors: str | None = None,
    ):
        self._file = tempfile.NamedTemporaryFile(
            mode=mode,
            encoding=encoding,
            newline=newline,
            buffering=buffering,
            suffix=suffix,
            prefix=prefix,
            dir=dir,
            errors=errors,
        )
        self.compression = compression
        self.bytes_total = 0
        self.records_total = 0
        self.bytes_since_last_reset = 0
        self.records_since_last_reset = 0
        self._brotli_compressor = None

    def __getattr__(self, name):
        """Pass get attr to underlying tempfile.NamedTemporaryFile."""
        return self._file.__getattr__(name)

    def __enter__(self):
        """Context-manager protocol enter method."""
        self._file.__enter__()
        return self

    def __exit__(self, exc, value, tb):
        """Context-manager protocol exit method."""
        self._file.__exit__(exc, value, tb)
        return False

    def __iter__(self):
        yield from self._file

    def __str__(self) -> str:
        return self._file.name

    @property
    def brotli_compressor(self):
        if self._brotli_compressor is None:
            self._brotli_compressor = brotli.Compressor()
        return self._brotli_compressor

    def finish_brotli_compressor(self):
        """Flush remaining brotli bytes."""
        # TODO: Move compression out of `BatchExportTemporaryFile` to a standard class for all writers.
        if self.compression != "brotli":
            raise ValueError(f"Compression is '{self.compression}', not 'brotli'")

        result = self._file.write(self.brotli_compressor.finish())
        self.bytes_total += result
        self.bytes_since_last_reset += result
        self._brotli_compressor = None

    def compress(self, content: bytes | str) -> bytes:
        if isinstance(content, str):
            encoded = content.encode("utf-8")
        else:
            encoded = content

        match self.compression:
            case "gzip":
                return gzip.compress(encoded)
            case "brotli":
                self.brotli_compressor.process(encoded)
                return self.brotli_compressor.flush()
            case None:
                return encoded
            case _:
                raise ValueError(f"Unsupported compression: '{self.compression}'")

    def write(self, content: bytes | str):
        """Write bytes to underlying file keeping track of how many bytes were written."""
        compressed_content = self.compress(content)

        if "b" in self.mode:
            result = self._file.write(compressed_content)
        else:
            result = self._file.write(compressed_content.decode("utf-8"))

        self.bytes_total += result
        self.bytes_since_last_reset += result

        return result

    def write_record_as_bytes(self, record: bytes):
        result = self.write(record)

        self.records_total += 1
        self.records_since_last_reset += 1

        return result

    def write_records_to_jsonl(self, records):
        """Write records to a temporary file as JSONL."""
        if len(records) == 1:
            try:
                jsonl_dump = orjson.dumps(records[0], option=orjson.OPT_APPEND_NEWLINE, default=str)
            except orjson.JSONEncodeError:
                # orjson is very strict about invalid unicode. This slow path protects us against
                # things we've observed in practice, like single surrogate codes, e.g. "\ud83d"
                cleaned_record = replace_broken_unicode(records[0])
                jsonl_dump = orjson.dumps(cleaned_record, option=orjson.OPT_APPEND_NEWLINE, default=str)
        else:
            jsonl_dump = b"\n".join(map(json_dumps_bytes, records))

        result = self.write(jsonl_dump)

        self.records_total += len(records)
        self.records_since_last_reset += len(records)

        return result

    def write_records_to_csv(
        self,
        records,
        fieldnames: None | collections.abc.Sequence[str] = None,
        extrasaction: typing.Literal["raise", "ignore"] = "ignore",
        delimiter: str = ",",
        quotechar: str = '"',
        escapechar: str | None = "\\",
        lineterminator: str = "\n",
        quoting=csv.QUOTE_NONE,
    ):
        """Write records to a temporary file as CSV."""
        if len(records) == 0:
            return

        if fieldnames is None:
            fieldnames = list(records[0].keys())

        writer = csv.DictWriter(
            self,
            fieldnames=fieldnames,
            extrasaction=extrasaction,
            delimiter=delimiter,
            quotechar=quotechar,
            escapechar=escapechar,
            quoting=quoting,
            lineterminator=lineterminator,
        )
        writer.writerows(records)

        self.records_total += len(records)
        self.records_since_last_reset += len(records)

    def write_records_to_tsv(
        self,
        records,
        fieldnames: None | list[str] = None,
        extrasaction: typing.Literal["raise", "ignore"] = "ignore",
        quotechar: str = '"',
        escapechar: str | None = "\\",
        lineterminator: str = "\n",
        quoting=csv.QUOTE_NONE,
    ):
        """Write records to a temporary file as TSV."""
        return self.write_records_to_csv(
            records,
            fieldnames=fieldnames,
            extrasaction=extrasaction,
            delimiter="\t",
            quotechar=quotechar,
            escapechar=escapechar,
            quoting=quoting,
            lineterminator=lineterminator,
        )

    def rewind(self):
        """Rewind the file before reading it."""
        self._file.seek(0)

    def reset(self):
        """Reset underlying file by truncating it.

        Also resets the tracker attributes for bytes and records since last reset.
        """
        self._file.seek(0)
        self._file.truncate()

        self.bytes_since_last_reset = 0
        self.records_since_last_reset = 0


IsLast = bool
RecordsSinceLastFlush = int
BytesSinceLastFlush = int
FlushCounter = int
FlushCallable = collections.abc.Callable[
    [
        BatchExportTemporaryFile,
        RecordsSinceLastFlush,
        BytesSinceLastFlush,
        FlushCounter,
        DateRange,
        IsLast,
        Exception | None,
    ],
    collections.abc.Awaitable[None],
]


class UnsupportedFileFormatError(Exception):
    """Raised when a writer for an unsupported file format is requested."""

    def __init__(self, file_format: str, destination: str):
        super().__init__(f"{file_format} is not a supported format for {destination} batch exports.")


class BatchExportWriter(abc.ABC):
    """A temporary file writer to be used by batch export workflows.

    Subclasses should define `_write_record_batch` with the particular intricacies
    of the format they are writing as.

    Actual writing calls are passed to the underlying `batch_export_file`.

    Attributes:
        _batch_export_file: The temporary file we are writing to.
        max_bytes: Flush the temporary file with the provided `flush_callable`
            upon reaching or surpassing this threshold. Keep in mind we write on a RecordBatch
            per RecordBatch basis, which means the threshold will be surpassed by at most the
            size of a RecordBatch before a flush occurs.
        flush_callable: A callback to flush the temporary file when `max_bytes` is reached.
            The temporary file will be reset after calling `flush_callable`. When calling
            `flush_callable` the following positional arguments will be passed: The temporary file
            that must be flushed, the number of records since the last flush, the number of bytes
            since the last flush, the latest recorded `_inserted_at`, and a `bool` indicating if
            this is the last flush (when exiting the context manager).
        file_kwargs: Optional keyword arguments passed when initializing `_batch_export_file`.
        last_inserted_at: Latest `_inserted_at` written. This attribute leaks some implementation
            details, as we are assuming assume `_inserted_at` is present, as it's added to all
            batch export queries.
        records_total: The total number of records (not RecordBatches!) written.
        records_since_last_flush: The number of records written since last flush.
        bytes_total: The total number of bytes written.
        bytes_since_last_flush: The number of bytes written since last flush.
    """

    def __init__(
        self,
        flush_callable: FlushCallable,
        max_bytes: int,
        file_kwargs: collections.abc.Mapping[str, typing.Any] | None = None,
    ):
        self.flush_callable = flush_callable
        self.max_bytes = max_bytes
        self.file_kwargs: collections.abc.Mapping[str, typing.Any] = file_kwargs or {}

        self._batch_export_file: BatchExportTemporaryFile | None = None
        self.reset_writer_tracking()

    def reset_writer_tracking(self):
        """Reset this writer's tracking state."""
        self.last_batch_start_at: dt.datetime | None = None
        self.last_batch_end_at: dt.datetime | None = None
        self.records_total = 0
        self.records_since_last_flush = 0
        self.bytes_total = 0
        self.bytes_since_last_flush = 0
        self.flush_counter = 0
        self.error = None

    @property
    def last_date_range(self) -> tuple[dt.datetime, dt.datetime] | None:
        if self.last_batch_start_at is not None and self.last_batch_end_at is not None:
            return (self.last_batch_start_at, self.last_batch_end_at)
        else:
            return None

    @contextlib.asynccontextmanager
    async def open_temporary_file(self, current_flush_counter: int = 0):
        """Explicitly open the temporary file this writer is writing to.

        The underlying `BatchExportTemporaryFile` is only accessible within this context manager. This helps
        us separate the lifetime of the underlying temporary file from the writer: The writer may still be
        accessed even after the temporary file is closed, while on the other hand we ensure the file and all
        its data is flushed and not leaked outside the context. Any relevant tracking information is copied
        to the writer.
        """
        self.reset_writer_tracking()
        self.flush_counter = current_flush_counter

        with BatchExportTemporaryFile(**self.file_kwargs) as temp_file:
            self._batch_export_file = temp_file

            try:
                yield

            except Exception as temp_err:
                self.error = temp_err
                raise

            finally:
                self.track_bytes_written(temp_file)

                if self.last_date_range is not None and self.bytes_since_last_flush > 0:
                    # `bytes_since_last_flush` should be 0 unless:
                    # 1. The last batch wasn't flushed as it didn't reach `max_bytes`.
                    # 2. The last batch was flushed but there was another write after the last call to
                    #    `write_record_batch`. For example, footer bytes.
                    await self.flush(self.last_date_range, is_last=True)

                self._batch_export_file = None

    @property
    def batch_export_file(self):
        """Property for underlying temporary file.

        Raises:
            ValueError: if attempting to access the temporary file before it has been opened.
        """
        if self._batch_export_file is None:
            raise ValueError("Batch export file is closed. Did you forget to call 'open_temporary_file'?")
        return self._batch_export_file

    @abc.abstractmethod
    def _write_record_batch(self, record_batch: pa.RecordBatch) -> None:
        """Write a record batch to the underlying `BatchExportTemporaryFile`.

        Subclasses must override this to provide the actual implementation according to the supported
        file format.
        """
        pass

    def track_records_written(self, record_batch: pa.RecordBatch) -> None:
        """Update this writer's state with the number of records in `record_batch`."""
        self.records_total += record_batch.num_rows
        self.records_since_last_flush += record_batch.num_rows

    def track_bytes_written(self, batch_export_file: BatchExportTemporaryFile) -> None:
        """Update this writer's state with the bytes in `batch_export_file`."""
        self.bytes_total = batch_export_file.bytes_total
        self.bytes_since_last_flush = batch_export_file.bytes_since_last_reset

    async def write_record_batch(self, record_batch: pa.RecordBatch, flush: bool = True) -> None:
        """Issue a record batch write tracking progress and flushing if required."""
        record_batch = record_batch.sort_by("_inserted_at")

        if self.last_batch_start_at is None:
            raw_start_at = record_batch.column("_inserted_at")[0].as_py()
            if isinstance(raw_start_at, int):
                try:
                    self.last_batch_start_at = dt.datetime.fromtimestamp(raw_start_at, tz=dt.UTC)
                except Exception:
                    raise
            else:
                self.last_batch_start_at = raw_start_at

        raw_end_at = record_batch.column("_inserted_at")[-1].as_py()
        if isinstance(raw_end_at, int):
            self.last_batch_end_at = dt.datetime.fromtimestamp(raw_end_at, tz=dt.UTC)
        else:
            self.last_batch_end_at = raw_end_at

        column_names = record_batch.column_names
        column_names.pop(column_names.index("_inserted_at"))

        await asyncio.to_thread(self._write_record_batch, record_batch.select(column_names))

        self.track_records_written(record_batch)
        self.track_bytes_written(self.batch_export_file)

        if flush and self.should_flush():
            await self.flush(self.last_date_range)

    def should_flush(self) -> bool:
        return self.bytes_since_last_flush >= self.max_bytes

    async def flush(self, last_date_range: tuple[dt.datetime, dt.datetime], is_last: bool = False) -> None:
        """Call the provided `flush_callable` and reset underlying file.

        The underlying batch export temporary file will be reset after calling `flush_callable`.
        """
        if is_last is True and self.batch_export_file.compression == "brotli":
            self.batch_export_file.finish_brotli_compressor()

        self.batch_export_file.seek(0)

        await self.flush_callable(
            self.batch_export_file,
            self.records_since_last_flush,
            self.bytes_since_last_flush,
            self.flush_counter,
            last_date_range,
            is_last,
            self.error,
        )
        self.batch_export_file.reset()

        self.records_since_last_flush = 0
        self.bytes_since_last_flush = 0
        self.flush_counter += 1
        self.last_batch_start_at = None
        self.last_batch_end_at = None


class JSONLBatchExportWriter(BatchExportWriter):
    """A `BatchExportWriter` for JSONLines format.

    Attributes:
        default: The default function to use to cast non-serializable Python objects to serializable objects.
            By default, non-serializable objects will be cast to string via `str()`.
    """

    def __init__(
        self,
        max_bytes: int,
        flush_callable: FlushCallable,
        compression: None | str = None,
        default: typing.Callable = str,
    ):
        super().__init__(
            max_bytes=max_bytes,
            flush_callable=flush_callable,
            file_kwargs={"compression": compression},
        )

        self.default = default

    def write_dict(self, d: dict[str, typing.Any]) -> int:
        """Write a single row of JSONL."""
        try:
            n = self.batch_export_file.write(orjson.dumps(d, default=str) + b"\n")
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
                        dumped = json.dumps(d, default=str).encode("utf-8")
                        n = self.batch_export_file.write(dumped + b"\n")
                    else:
                        dumped = orjson.dumps(d, default=str)
                        n = self.batch_export_file.write(dumped + b"\n")

                else:
                    # In this case, we fallback to the slower but more permissive stdlib
                    # json.
                    logger.exception("Orjson detected a deeply nested dict: %s", d)
                    dumped = json.dumps(d, default=str).encode("utf-8")
                    n = self.batch_export_file.write(dumped + b"\n")
            else:
                # Orjson is very strict about invalid unicode. This slow path protects us
                # against things we've observed in practice, like single surrogate codes, e.g.
                # "\ud83d"
                logger.exception("Failed to encode with orjson: %s", d)
                cleaned_content = replace_broken_unicode(d)
                n = self.batch_export_file.write(orjson.dumps(cleaned_content, default=str) + b"\n")
        return n

    def _write_record_batch(self, record_batch: pa.RecordBatch) -> None:
        """Write records to a temporary file as JSONL."""
        for record_dict in record_batch.to_pylist():
            if not record_dict:
                continue

            self.write_dict(record_dict)


class CSVBatchExportWriter(BatchExportWriter):
    """A `BatchExportWriter` for CSV format."""

    def __init__(
        self,
        max_bytes: int,
        flush_callable: FlushCallable,
        field_names: collections.abc.Sequence[str],
        extras_action: typing.Literal["raise", "ignore"] = "ignore",
        delimiter: str = ",",
        quote_char: str = '"',
        escape_char: str | None = "\\",
        line_terminator: str = "\n",
        quoting=csv.QUOTE_NONE,
        compression: str | None = None,
    ):
        super().__init__(
            max_bytes=max_bytes,
            flush_callable=flush_callable,
            file_kwargs={"compression": compression},
        )
        self.field_names = field_names
        self.extras_action: typing.Literal["raise", "ignore"] = extras_action
        self.delimiter = delimiter
        self.quote_char = quote_char
        self.escape_char = escape_char
        self.line_terminator = line_terminator
        self.quoting = quoting

        self._csv_writer: csv.DictWriter | None = None

    @property
    def csv_writer(self) -> csv.DictWriter:
        if self._csv_writer is None:
            self._csv_writer = csv.DictWriter(
                self.batch_export_file,
                fieldnames=self.field_names,
                extrasaction=self.extras_action,
                delimiter=self.delimiter,
                quotechar=self.quote_char,
                escapechar=self.escape_char,
                quoting=self.quoting,
                lineterminator=self.line_terminator,
            )

        return self._csv_writer

    def _write_record_batch(self, record_batch: pa.RecordBatch) -> None:
        """Write records to a temporary file as CSV."""
        self.csv_writer.writerows(record_batch.to_pylist())


class ParquetBatchExportWriter(BatchExportWriter):
    """A `BatchExportWriter` for Apache Parquet format.

    We utilize and wrap a `pyarrow.parquet.ParquetWriter` to do the actual writing. We default to their
    defaults for most parameters; however this class could be extended with more attributes to pass along
    to `pyarrow.parquet.ParquetWriter`.

    See the pyarrow docs for more details on what parameters can the writer be configured with:
    https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetWriter.html

    In contrast to other writers, instead of us handling compression we let `pyarrow.parquet.ParquetWriter`
    handle it, so `BatchExportTemporaryFile` is always initialized with `compression=None`.

    Attributes:
        schema: The schema used by the Parquet file. Should match the schema of written RecordBatches.
        compression: Compression codec passed to underlying `pyarrow.parquet.ParquetWriter`.
    """

    def __init__(
        self,
        max_bytes: int,
        flush_callable: FlushCallable,
        schema: pa.Schema,
        compression: str | None = "snappy",
    ):
        super().__init__(
            max_bytes=max_bytes,
            flush_callable=flush_callable,
            file_kwargs={"compression": None},  # ParquetWriter handles compression
        )
        self.schema = schema
        self.compression = compression

        self._parquet_writer: pq.ParquetWriter | None = None

    @property
    def parquet_writer(self) -> pq.ParquetWriter:
        if self._parquet_writer is None:
            self._parquet_writer = pq.ParquetWriter(
                self.batch_export_file,
                schema=self.schema,
                compression="none" if self.compression is None else self.compression,
            )
        return self._parquet_writer

    @contextlib.asynccontextmanager
    async def open_temporary_file(self, current_flush_counter: int = 0):
        """Ensure underlying Parquet writer is closed before flushing and closing temporary file."""
        async with super().open_temporary_file(current_flush_counter):
            try:
                yield
            finally:
                if self._parquet_writer is not None:
                    self._parquet_writer.writer.close()
                    self._parquet_writer = None

    def _write_record_batch(self, record_batch: pa.RecordBatch) -> None:
        """Write records to a temporary file as Parquet."""

        self.parquet_writer.write_batch(record_batch.select(self.parquet_writer.schema.names))
