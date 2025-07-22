from dataclasses import dataclass


@dataclass
class BatchExportResult:
    # This is the total number of records that were successfully exported
    # (not the number of record batches, but the number of records in all record batches)
    records_completed: int | None = None
    # This is the number of bytes of data exported (i.e. not the number of bytes in ClickHouse or the internal stage)
    # and therefore takes into account things like the file type and compression
    bytes_exported: int | None = None
    # This is the error that occurred, if any
    error: str | None = None

    @classmethod
    def from_exception(cls, e: Exception) -> "BatchExportResult":
        return cls(error=f"{e.__class__.__name__}: {e}")
