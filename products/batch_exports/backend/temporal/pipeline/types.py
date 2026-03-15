import collections.abc
from dataclasses import dataclass


@dataclass
class BatchExportError:
    type: str
    message: str


@dataclass
class BatchExportResult:
    """Result of a batch export execution.

    Attributes:
        records_completed: Total number of records that were successfully exported. Not
            the number of record batches, but the number of records in all record
            batches.
        bytes_exported: This is the number of bytes of data exported (i.e. not the
            number of bytes in ClickHouse or the internal stage) and therefore takes
            into account things like the file type and compression.
        error: Error or errors that occurred, if any.
    """

    records_completed: int | None = None
    bytes_exported: int | None = None
    error: BatchExportError | list[BatchExportError] | None = None

    @property
    def error_repr(self) -> str | None:
        match self.error:
            case [*errors]:
                return ",".join(f"{error.type}: {error.message}" for error in errors)
            case None:
                return None
            case error:
                # mypy cannot narrow types properly, error can only be BatchExportError
                # See: https://github.com/python/mypy/issues/19081
                return f"{error.type}: {error.message}"  # type: ignore[union-attr]

    @classmethod
    def from_exception(cls, e: Exception) -> "BatchExportResult":
        return cls(error=BatchExportError(type=e.__class__.__name__, message=str(e)))


def reduce_batch_export_results(results: collections.abc.Iterable[BatchExportResult]) -> BatchExportResult:
    records_completed = 0
    bytes_exported = 0
    error: list[BatchExportError] = []

    for result in results:
        if result.records_completed is not None:
            records_completed += result.records_completed

        if result.bytes_exported is not None:
            bytes_exported += result.bytes_exported

        if result.error is not None:
            # TODO: Consolidate errors of the same type into one
            if not isinstance(result.error, list):
                errors = [result.error]
            else:
                errors = result.error

            error.extend(errors)

    return BatchExportResult(
        records_completed=records_completed,
        bytes_exported=bytes_exported,
        error=error or None,
    )
