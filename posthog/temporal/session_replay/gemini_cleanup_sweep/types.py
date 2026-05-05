from dataclasses import dataclass
from datetime import datetime


@dataclass
class CleanupSweepInputs:
    pass


@dataclass
class CleanupSweepResult:
    scanned: int = 0
    deleted: int = 0
    skipped_running: int = 0
    skipped_too_young: int = 0
    skipped_temporal_error: int = 0
    skipped_invalid_value: int = 0
    delete_failed: int = 0
    hit_max_files_cap: bool = False


@dataclass(frozen=True)
class TrackedFile:
    gemini_file_name: str
    workflow_id: str
    uploaded_at: datetime
