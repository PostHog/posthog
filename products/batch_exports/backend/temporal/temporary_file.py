"""This module contains a temporary file to stage data in batch exports."""

import abc
import csv
import enum
import gzip
import json
import typing
import asyncio
import datetime as dt
import tempfile
import contextlib
import collections.abc

import brotli
import orjson
import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
from psycopg import sql

from posthog.temporal.common.logger import get_write_only_logger

from products.batch_exports.backend.temporal.heartbeat import DateRange

logger = get_write_only_logger()


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
    except orjson.JSONEncodeError as e:
        if str(e) == "Integer exceeds 64-bit range":
            logger.warning("Failed to encode with orjson: Integer exceeds 64-bit range: %s", d)
            # orjson doesn't support integers exceeding 64-bit range, so we fall back to json.dumps
            # see https://github.com/ijl/orjson/issues/301
            return json.dumps(d, default=str).encode("utf-8")
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
        max_file_size_bytes: Flush the temporary file with the provided `flush_callable`
            upon reaching or surpassing this threshold. This results in a 'hard flush' of the
            temporary file, which means the file will be closed and a new one will be created.
            If set to 0, this will be ignored.
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
        max_file_size_bytes: int = 0,
        file_kwargs: collections.abc.Mapping[str, typing.Any] | None = None,
    ):
        self.flush_callable = flush_callable
        self.max_bytes = max_bytes
        self.max_file_size_bytes = max_file_size_bytes
        self.file_kwargs: collections.abc.Mapping[str, typing.Any] = file_kwargs or {}

        self._batch_export_file: BatchExportTemporaryFile | None = None
        self.reset_writer_tracking()

    def reset_writer_tracking(self):
        """Reset this writer's tracking state."""
        self.start_at_since_last_flush: dt.datetime | None = None
        self.end_at_since_last_flush: dt.datetime | None = None
        self.flushed_date_ranges: list[DateRange] = []
        self.records_total = 0
        self.records_since_last_flush = 0
        self.bytes_total = 0
        self.bytes_since_last_flush = 0
        self.flush_counter = 0
        self.error = None

    @property
    def date_range_since_last_flush(self) -> DateRange | None:
        if self.start_at_since_last_flush is not None and self.end_at_since_last_flush is not None:
            return (self.start_at_since_last_flush, self.end_at_since_last_flush)
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

        with self.create_temporary_file() as temp_file:
            self._batch_export_file = temp_file

            try:
                yield self

            except Exception as temp_err:
                self.error = temp_err
                raise

            finally:
                await self.close_temporary_file()

    async def close_temporary_file(self):
        self.track_bytes_written(self.batch_export_file)

        if self.bytes_since_last_flush > 0:
            # `bytes_since_last_flush` should be 0 unless:
            # 1. The last batch wasn't flushed as it didn't reach `max_bytes`.
            # 2. The last batch was flushed but there was another write after the last call to
            #    `write_record_batch`. For example, footer bytes.
            await self.flush(is_last=True)

        self._batch_export_file = None

    def create_temporary_file(self) -> BatchExportTemporaryFile:
        return BatchExportTemporaryFile(**self.file_kwargs)

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

    async def write_record_batch(
        self, record_batch: pa.RecordBatch, flush: bool = True, include_inserted_at: bool = False
    ) -> None:
        """Issue a record batch write tracking progress and flushing if required."""
        record_batch = record_batch.sort_by("_inserted_at")

        if self.start_at_since_last_flush is None:
            raw_start_at = record_batch.column("_inserted_at")[0].as_py()
            if isinstance(raw_start_at, int):
                try:
                    self.start_at_since_last_flush = dt.datetime.fromtimestamp(raw_start_at, tz=dt.UTC)
                except Exception:
                    raise
            else:
                self.start_at_since_last_flush = raw_start_at

        raw_end_at = record_batch.column("_inserted_at")[-1].as_py()
        if isinstance(raw_end_at, int):
            self.end_at_since_last_flush = dt.datetime.fromtimestamp(raw_end_at, tz=dt.UTC)
        else:
            self.end_at_since_last_flush = raw_end_at

        column_names = record_batch.column_names
        if not include_inserted_at:
            column_names.pop(column_names.index("_inserted_at"))

        await asyncio.to_thread(self._write_record_batch, record_batch.select(column_names))

        self.track_records_written(record_batch)
        self.track_bytes_written(self.batch_export_file)

        if flush and self.should_flush():
            await self.flush()

    def should_flush(self) -> bool:
        return self.bytes_since_last_flush >= self.max_bytes

    def should_hard_flush(self) -> bool:
        return self.max_file_size_bytes > 0 and self.bytes_total >= self.max_file_size_bytes

    async def flush(self, is_last: bool = False) -> None:
        """Call the provided `flush_callable` and reset underlying file.

        The underlying batch export temporary file will be reset after calling `flush_callable`.
        """
        if is_last is True and self.batch_export_file.compression == "brotli":
            self.batch_export_file.finish_brotli_compressor()

        self.batch_export_file.seek(0)

        if self.date_range_since_last_flush is not None:
            self.flushed_date_ranges.append(self.date_range_since_last_flush)

        await self.flush_callable(
            self.batch_export_file,
            self.records_since_last_flush,
            self.bytes_since_last_flush,
            self.flush_counter,
            self.flushed_date_ranges[-1],
            is_last,
            self.error,
        )
        self.batch_export_file.reset()

        self.records_since_last_flush = 0
        self.bytes_since_last_flush = 0
        self.flush_counter += 1
        self.start_at_since_last_flush = None
        self.end_at_since_last_flush = None

    async def hard_flush(self):
        """Flush the underlying file by closing the temporary file and creating a new one.

        This is useful is we want to write a whole file, rather than flushing a
        part of it for example.
        """
        await self.close_temporary_file()
        self._batch_export_file = await asyncio.to_thread(self.create_temporary_file)


class WriterFormat(enum.StrEnum):
    JSONL = enum.auto()
    PARQUET = enum.auto()
    CSV = enum.auto()
    REDSHIFT_INSERT = enum.auto()

    @staticmethod
    def from_str(format_str: str, destination: str):
        match format_str.upper():
            case "JSONL" | "JSONLINES":
                return WriterFormat.JSONL
            case "PARQUET":
                return WriterFormat.PARQUET
            case "CSV":
                return WriterFormat.CSV
            case "REDSHIFT_INSERT":
                return WriterFormat.REDSHIFT_INSERT
            case _:
                raise UnsupportedFileFormatError(format_str, destination)


def get_batch_export_writer(
    writer_format: WriterFormat, flush_callable: FlushCallable, max_bytes: int, max_file_size_bytes: int = 0, **kwargs
):
    match writer_format:
        case WriterFormat.CSV:
            return CSVBatchExportWriter(
                max_bytes=max_bytes,
                flush_callable=flush_callable,
                max_file_size_bytes=max_file_size_bytes,
                **kwargs,
            )

        case WriterFormat.JSONL:
            return JSONLBatchExportWriter(
                max_bytes=max_bytes,
                flush_callable=flush_callable,
                max_file_size_bytes=max_file_size_bytes,
                **kwargs,
            )

        case WriterFormat.PARQUET:
            return ParquetBatchExportWriter(
                max_bytes=max_bytes,
                flush_callable=flush_callable,
                max_file_size_bytes=max_file_size_bytes,
                **kwargs,
            )

        case WriterFormat.REDSHIFT_INSERT:
            return RedshiftInsertBatchExportWriter(
                max_bytes=max_bytes,
                flush_callable=flush_callable,
                **kwargs,
            )


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
        schema: pa.Schema | None = None,
        compression: None | str = None,
        default: typing.Callable = str,
        max_file_size_bytes: int = 0,
    ):
        super().__init__(
            max_bytes=max_bytes,
            flush_callable=flush_callable,
            file_kwargs={"compression": compression},
            max_file_size_bytes=max_file_size_bytes,
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
        schema: pa.Schema | None = None,
        extras_action: typing.Literal["raise", "ignore"] = "ignore",
        delimiter: str = ",",
        quote_char: str = '"',
        escape_char: str | None = "\\",
        line_terminator: str = "\n",
        quoting=csv.QUOTE_NONE,
        compression: str | None = None,
        max_file_size_bytes: int = 0,
    ):
        super().__init__(
            max_bytes=max_bytes,
            flush_callable=flush_callable,
            file_kwargs={"compression": compression},
            max_file_size_bytes=max_file_size_bytes,
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

    async def close_temporary_file(self):
        """Ensure underlying `DictWriter` is closed before flushing and closing temporary file."""
        if self._csv_writer is not None:
            self._csv_writer = None

        await super().close_temporary_file()

    def _write_record_batch(self, record_batch: pa.RecordBatch) -> None:
        """Write records to a temporary file as CSV.

        Since this writer is only used in the PostgreSQL batch export, we do a
        replacement of [] for {} to support PostgreSQL literal arrays when writing
        a list.
        """
        rows = []
        for record in record_batch.to_pylist():
            rows.append({k: ensure_curly_brackets_array(v) if isinstance(v, list) else v for k, v in record.items()})
        self.csv_writer.writerows(rows)


def ensure_curly_brackets_array(v: list[typing.Any]) -> str:
    """Convert list to str and replace ends with curly braces."""
    # NOTE: This doesn't support nested arrays (i.e. multi-dimensional arrays).
    str_list = str(v)
    return f"{{{str_list[1:len(str_list)-1]}}}"


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
        compression_level: int | None = None,
        max_file_size_bytes: int = 0,
    ):
        super().__init__(
            max_bytes=max_bytes,
            flush_callable=flush_callable,
            file_kwargs={"compression": None},  # ParquetWriter handles compression
            max_file_size_bytes=max_file_size_bytes,
        )
        self.schema = schema
        self.compression = compression
        self.compression_level = compression_level
        self._parquet_writer: pq.ParquetWriter | None = None

    @property
    def parquet_writer(self) -> pq.ParquetWriter:
        if self._parquet_writer is None:
            self._parquet_writer = pq.ParquetWriter(
                self.batch_export_file,
                schema=self.schema,
                compression="none" if self.compression is None else self.compression,  # type: ignore
                compression_level=self.compression_level,
            )
        return self._parquet_writer

    async def close_temporary_file(self):
        """Ensure underlying Parquet writer is closed before flushing and closing temporary file."""
        if self._parquet_writer is not None:
            self._parquet_writer.writer.close()
            self._parquet_writer = None

        await super().close_temporary_file()

    def _write_record_batch(self, record_batch: pa.RecordBatch) -> None:
        """Write records to a temporary file as Parquet."""

        self.parquet_writer.write_batch(record_batch.select(self.parquet_writer.schema.names))


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


class RedshiftInsertBatchExportWriter(BatchExportWriter):
    """A `BatchExportWriter` for Redshift INSERT queries.

    Arguments:
        max_bytes: Redshift's SQL statement size limit is 16MB, so anything more than
            that will result in an error. However, setthing `max_bytes` too low can
            significantly affect performance due to Redshift's poor handling of INSERTs.
    """

    def __init__(
        self,
        max_bytes: int,
        flush_callable: FlushCallable,
        schema: pa.Schema,
        redshift_table: str,
        redshift_schema: str | None,
        table_columns: collections.abc.Sequence[str],
        known_json_columns: collections.abc.Sequence[str],
        use_super: bool,
        redshift_client,
    ):
        super().__init__(
            max_bytes=max_bytes,
            flush_callable=flush_callable,
            file_kwargs={"compression": None},
        )
        self.schema = schema
        self.redshift_table = redshift_table
        self.redshift_schema = redshift_schema
        self.table_columns = table_columns
        self.known_json_columns = known_json_columns
        self.use_super = use_super
        self.redshift_client = redshift_client
        self._cursor: psycopg.AsyncClientCursor | None = None
        self.first = True

        placeholders: list[sql.Composable] = []
        for column in table_columns:
            if column in known_json_columns and use_super is True:
                placeholders.append(sql.SQL("JSON_PARSE({placeholder})").format(placeholder=sql.Placeholder(column)))
            else:
                placeholders.append(sql.Placeholder(column))

        self.template = sql.SQL("({})").format(sql.SQL(", ").join(placeholders))

    def create_temporary_file(self) -> BatchExportTemporaryFile:
        """On creating a temporary file, write first the start of a query."""
        file = super().create_temporary_file()

        if self.redshift_schema:
            table_identifier = sql.Identifier(self.redshift_schema, self.redshift_table)
        else:
            table_identifier = sql.Identifier(self.redshift_table)

        pre_query_encoded = asyncio.run(self.get_encoded_pre_query(table_identifier))
        file.write(pre_query_encoded)

        return file

    async def get_encoded_pre_query(self, table_identifier: sql.Identifier) -> bytes:
        """Encode and format the start of an INSERT INTO query."""
        pre_query = sql.SQL("INSERT INTO {table} ({fields}) VALUES").format(
            table=table_identifier,
            fields=sql.SQL(", ").join(map(sql.Identifier, self.table_columns)),
        )

        async with self.redshift_client.async_client_cursor() as cursor:
            return pre_query.as_string(cursor).encode("utf-8")

    def _write_record_batch(self, record_batch: pa.RecordBatch) -> None:
        """Write records to a temporary file as values in an INSERT query."""
        for record_dict in record_batch.to_pylist():
            if not record_dict:
                continue

            record = {}
            for key, value in record_dict.items():
                if key not in self.table_columns:
                    continue

                record[key] = value

                if value is not None and key in self.known_json_columns:
                    record[key] = json.dumps(remove_escaped_whitespace_recursive(record[key]), ensure_ascii=False)

            encoded = asyncio.run(self.mogrify_record(record))

            if self.first:
                self.first = False
            else:
                self.batch_export_file.write(",")

            self.batch_export_file.write(encoded)

    async def mogrify_record(self, record: dict[str, typing.Any]) -> bytes:
        """Produce encoded bytes from a record."""
        async with self.redshift_client.async_client_cursor() as cursor:
            return cursor.mogrify(self.template, record).encode("utf-8").replace(b" E'", b" '")

    async def close_temporary_file(self):
        """Ensure we mark next query as first after closing a file."""
        await super().close_temporary_file()
        self.first = True
