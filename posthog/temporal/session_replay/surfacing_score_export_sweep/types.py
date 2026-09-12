"""Workflow payloads carry partition coordinates and page cursors; score rows stay in activities."""

from dataclasses import dataclass, field

from posthog.dataclasses import frozen


@dataclass
class ExportScoresSweepInputs:
    pass


@dataclass(frozen=True)
class ExportPartitionSpec:
    day: str  # YYYY-MM-DD (UTC)
    chunk_id: int
    of_chunks: int
    legacy_only: bool = False
    encrypted_enabled: bool = False


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


@frozen
class EncryptedScorePage:
    partition: ExportPartitionSpec
    export_id: str
    page: int = 0
    cursor_session_id: str = ""
    cursor_team_id: int = 0


@frozen
class EncryptedScorePageResult:
    rows: int
    bytes_written: int
    next_page: EncryptedScorePage | None
