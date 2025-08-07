from dataclasses import dataclass


@dataclass
class BatchExportError:
    type: str
    message: str


@dataclass
class BatchExportResult:
    # This is the total number of records that were successfully exported
    # (not the number of record batches, but the number of records in all record batches)
    records_completed: int | None = None
    # This is the number of bytes of data exported (i.e. not the number of bytes in ClickHouse or the internal stage)
    # and therefore takes into account things like the file type and compression
    bytes_exported: int | None = None
    # This is the error that occurred, if any
    error: BatchExportError | None = None

    @property
    def error_repr(self) -> str | None:
        if self.error:
            return f"{self.error.type}: {self.error.message}"
        return None

    @classmethod
    def from_exception(cls, e: Exception) -> "BatchExportResult":
        return cls(error=BatchExportError(type=e.__class__.__name__, message=str(e)))
