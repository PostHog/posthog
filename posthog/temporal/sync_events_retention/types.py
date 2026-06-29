from dataclasses import dataclass


@dataclass(frozen=True)
class SyncEventsRetentionInput:
    dry_run: bool
    batch_size: int = 1000
