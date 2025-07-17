import typing


class BatchExportResult(typing.NamedTuple):
    # This is the total number of records that were successfully exported
    # (not the number of record batches, but the number of records in all record batches)
    records_completed: int
    # This is the number of bytes of data exported (i.e. not the number of bytes in ClickHouse or the internal stage)
    # and therefore takes into account things like the file type and compression
    bytes_exported: int
