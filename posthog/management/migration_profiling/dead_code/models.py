"""Data models for dead-code findings."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Confidence(Enum):
    """Three named tiers a detector uses to label a finding.

    HIGH (≥ 0.9): mechanical — the finding is safe to act on after a glance.
    MEDIUM (0.5 – 0.9): plausible — needs a per-migration audit.
    LOW (< 0.5): suggestion — surface but don't bias toward acting.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @classmethod
    def from_score(cls, score: float) -> Confidence:
        if score >= 0.9:
            return cls.HIGH
        if score >= 0.5:
            return cls.MEDIUM
        return cls.LOW


@dataclass
class Finding:
    """A single detector hit."""

    detector_name: str
    kind: str  # short stable label, e.g. "add_remove_field_loop"
    summary: str  # one-line human-readable
    confidence: float  # 0.0 – 1.0
    # Migrations involved in this finding. First entry is conventionally the
    # one to delete or audit first.
    migrations: list[tuple[str, str]] = field(default_factory=list)  # [(app, migration_name)]
    detail: str = ""  # multi-line explanation / evidence
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def confidence_tier(self) -> Confidence:
        return Confidence.from_score(self.confidence)
