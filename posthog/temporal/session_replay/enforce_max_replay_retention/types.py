from dataclasses import dataclass


@dataclass(frozen=True)
class EnforceMaxReplayRetentionInput:
    dry_run: bool
    batch_size: int = 100
