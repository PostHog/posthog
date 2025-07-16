import typing


class BatchExportResult(typing.NamedTuple):
    records_completed: int
    bytes_exported: int
