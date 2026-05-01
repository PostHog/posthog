from dataclasses import dataclass


@dataclass
class CleanupSweepInputs:
    pass


@dataclass
class CleanupSweepResult:
    listed: int = 0
    deleted: int = 0
    skipped_running: int = 0
    skipped_too_young: int = 0
    skipped_unrecognized_prefix: int = 0
    skipped_no_name: int = 0
    skipped_temporal_error: int = 0
    delete_failed: int = 0
    hit_max_files_cap: bool = False
