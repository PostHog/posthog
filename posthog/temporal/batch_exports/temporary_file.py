"""This module contains a temporary file to stage data in batch exports."""
import abc
import collections.abc
import contextlib
import csv
import datetime as dt
import gzip
import tempfile
import typing

import brotli
import orjson
import pyarrow as pa
import pyarrow.parquet as pq


def json_dumps_bytes(d) -> bytes:
    return orjson.dumps(d, default=str)


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
        return self._file.__exit__(exc, value, tb)

    def __iter__(self):
        yield from self._file

    @property
    def brotli_compressor(self):
        if self._brotli_compressor is None:
            self._brotli_compressor = brotli.Compressor()
        return self._brotli_compressor

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
            jsonl_dump = orjson.dumps(records[0], option=orjson.OPT_APPEND_NEWLINE, default=str)
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
        if self.compression == "brotli":
            result = self._file.write(self.brotli_compressor.finish())

            self.bytes_total += result
            self.bytes_since_last_reset += result

            self._brotli_compressor = None

        self._file.seek(0)

    def reset(self):
        """Reset underlying file by truncating it.

        Also resets the tracker attributes for bytes and records since last reset.
        """
        self._file.seek(0)
        self._file.truncate()

        self.bytes_since_last_reset = 0
        self.records_since_last_reset = 0


FlushCallable = collections.abc.Callable[
    [BatchExportTemporaryFile, int, int, dt.datetime, bool], collections.abc.Awaitable[None]
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
        batch_export_file: The temporary file we are writing to.
        bytes_flush_threshold: Flush the temporary file with the provided `flush_callable`
            upon reaching or surpassing this threshold. Keep in mind we write on a RecordBatch
            per RecordBatch basis, which means the threshold will be surpassed by at most the
            size of a RecordBatch before a flush occurs.
        flush_callable: A callback to flush the temporary file when `bytes_flush_treshold` is reached.
            The temporary file will be reset after calling `flush_callable`.
        records_total: The total number of records (not RecordBatches!) written.
        records_since_last_flush: The number of records written since last flush.
        last_inserted_at: Latest `_inserted_at` written. This attribute leaks some implementation
            details, as we are making two assumptions about the RecordBatches being written:
                * We assume RecordBatches are sorted on `_inserted_at`, which currently happens with
                    an `ORDER BY` clause.
                * We assume `_inserted_at` is present, as it's added to all batch export queries.
    """

    def __init__(
        self,
        flush_callable: FlushCallable,
        max_bytes: int,
        file_kwargs: collections.abc.Mapping[str, typing.Any],
    ):
        self.flush_callable = flush_callable
        self.max_bytes = max_bytes
        self.file_kwargs = file_kwargs

        self._batch_export_file: BatchExportTemporaryFile | None = None
        self.reset_writer_tracking()

    def reset_writer_tracking(self):
        self.last_inserted_at: dt.datetime | None = None
        self.records_total = 0
        self.records_since_last_flush = 0
        self.bytes_total = 0
        self.bytes_since_last_flush = 0

    @contextlib.asynccontextmanager
    async def open_temporary_file(self):
        """Explicitly open the temporary file this writer is writing to.

        The underlying `BatchExportTemporaryFile` is only accessible within this context manager. This helps
        us separate the lifetime of the underlying temporary file from the writer: The writer may still be
        accessed even after the temporary file is closed, while on the other hand we ensure the file and all
        its data is flushed and not leaked outside the context. Any relevant tracking information
        """
        self.reset_writer_tracking()

        with BatchExportTemporaryFile(**self.file_kwargs) as temp_file:
            self._batch_export_file = temp_file

            try:
                yield
            finally:
                self.track_bytes_written(temp_file)

                if self.last_inserted_at is not None and self.bytes_since_last_flush > 0:
                    # `bytes_since_last_flush` should be 0 unless:
                    # 1. The last batch wasn't flushed as it didn't reach `max_bytes`.
                    # 2. The last batch was flushed but there was another write after the last call to
                    #    `write_record_batch`. For example, footer bytes.
                    await self.flush(self.last_inserted_at, is_last=True)

        self._batch_export_file = None

    @property
    def batch_export_file(self):
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
        self.records_total += record_batch.num_rows
        self.records_since_last_flush += record_batch.num_rows

    def track_bytes_written(self, batch_export_file: BatchExportTemporaryFile) -> None:
        self.bytes_total = batch_export_file.bytes_total
        self.bytes_since_last_flush = batch_export_file.bytes_since_last_reset

    async def write_record_batch(self, record_batch: pa.RecordBatch) -> None:
        """Issue a record batch write tracking progress and flushing if required."""
        last_inserted_at = record_batch.column("_inserted_at")[0].as_py()

        column_names = record_batch.column_names
        column_names.pop(column_names.index("_inserted_at"))

        self._write_record_batch(record_batch.select(column_names))

        self.last_inserted_at = last_inserted_at
        self.track_records_written(record_batch)
        self.track_bytes_written(self.batch_export_file)

        if self.bytes_since_last_flush >= self.max_bytes:
            await self.flush(last_inserted_at)

    async def flush(self, last_inserted_at: dt.datetime, is_last: bool = False) -> None:
        """Call the provided `flush_callable` and reset underlying file."""
        await self.flush_callable(
            self.batch_export_file,
            self.records_since_last_flush,
            self.bytes_since_last_flush,
            last_inserted_at,
            is_last,
        )
        self.batch_export_file.reset()

        self.records_since_last_flush = 0
        self.bytes_since_last_flush = 0


class JSONLBatchExportWriter(BatchExportWriter):
    """A `BatchExportWriter` for JSONLines format."""

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

    def write(self, content: bytes) -> int:
        n = self.batch_export_file.write(orjson.dumps(content, default=str) + b"\n")
        return n

    def _write_record_batch(self, record_batch: pa.RecordBatch) -> None:
        """Write records to a temporary file as JSONL."""
        for record in record_batch.to_pylist():
            self.write(record)


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
    """A `BatchExportWriter` for Apache Parquet format."""

    def __init__(
        self,
        max_bytes: int,
        flush_callable: FlushCallable,
        schema: pa.Schema,
        version: str = "2.6",
        compression: str | None = "snappy",
        compression_level: int | None = None,
    ):
        super().__init__(
            max_bytes=max_bytes,
            flush_callable=flush_callable,
            file_kwargs={"compression": None},  # ParquetWriter handles compression
        )
        self.schema = schema
        self.version = version
        self.compression = compression
        self.compression_level = compression_level

        self._parquet_writer: pq.ParquetWriter | None = None

    @property
    def parquet_writer(self) -> pq.ParquetWriter:
        if self._parquet_writer is None:
            self._parquet_writer = pq.ParquetWriter(
                self.batch_export_file,
                schema=self.schema,
                version=self.version,
                # Compression *can* be `None`.
                compression=self.compression,
                compression_level=self.compression_level,
            )
        return self._parquet_writer

    def ensure_parquet_writer_is_closed(self) -> None:
        """Ensure ParquetWriter is closed as Parquet footer bytes are written on closing."""
        if self._parquet_writer is None:
            return

        self._parquet_writer.writer.close()
        self._parquet_writer = None

    @contextlib.asynccontextmanager
    async def open_temporary_file(self):
        """Ensure underlying Parquet writer is closed before flushing and closing temporary file."""
        async with super().open_temporary_file():
            try:
                yield
            finally:
                self.ensure_parquet_writer_is_closed()

    def _write_record_batch(self, record_batch: pa.RecordBatch) -> None:
        """Write records to a temporary file as Parquet."""
        self.parquet_writer.write_batch(record_batch.select(self.parquet_writer.schema.names))
