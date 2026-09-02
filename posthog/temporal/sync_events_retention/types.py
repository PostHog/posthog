from dataclasses import dataclass
from typing import Optional

from posthog.slo.types import SloConfig


@dataclass(frozen=True)
class SyncEventsRetentionInput:
    dry_run: bool
    batch_size: int = 1000
    slo: Optional[SloConfig] = None


@dataclass(frozen=True)
class SyncEventsRetentionResult:
    total_processed: int
    total_updated: int
