"""Dataclasses for the surfacing-score export workflow inputs and outputs.

All payloads stay tiny (well under Temporal's ~2 MiB limit): specs carry a
day + hash-bucket id only, and results carry counts — session ids and scores
never flow through the workflow boundary.
"""

from dataclasses import dataclass, field


@dataclass
class ExportScoresSweepInputs:
    """Top-level workflow input. Empty by design — all sizing is in constants.py."""

    pass


@dataclass
class ExportPartitionSpec:
    """One (UTC day, hash bucket) slice of scored sessions to export.

    The activity re-queries ClickHouse for its slice, so fanning these out
    carries no payload pressure. `of_chunks` is baked into the object key so
    a resize can never half-overwrite an old layout.
    """

    day: str  # YYYY-MM-DD (UTC)
    chunk_id: int
    of_chunks: int


@dataclass
class ListExportPartitionsResult:
    partitions: list[ExportPartitionSpec] = field(default_factory=list)
    # Set when the export is not configured in this environment (no pseudonym
    # key / no S3 destination); the workflow logs and exits without failing.
    disabled_reason: str | None = None


@dataclass
class ExportPartitionResult:
    day: str
    chunk_id: int
    rows: int = 0
    bytes_written: int = 0
    key: str = ""


@dataclass
class ExportScoresSweepResult:
    partitions_dispatched: int = 0
    partitions_failed: int = 0
    total_rows: int = 0
    disabled_reason: str | None = None
