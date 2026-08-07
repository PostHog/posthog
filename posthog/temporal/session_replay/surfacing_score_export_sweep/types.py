"""Workflow inputs/outputs. Specs carry a day + hash bucket only — ids and scores never cross the workflow boundary."""

from dataclasses import dataclass, field


@dataclass
class ExportScoresSweepInputs:
    pass


@dataclass
class ExportPartitionSpec:
    day: str  # YYYY-MM-DD (UTC)
    chunk_id: int
    of_chunks: int


@dataclass
class ListExportPartitionsResult:
    partitions: list[ExportPartitionSpec] = field(default_factory=list)
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
