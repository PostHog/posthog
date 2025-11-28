"""Data models for migration risk analysis."""

from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(Enum):
    """Risk level definitions with scoring ranges"""

    SAFE = ("Safe", 0, 0)
    NEEDS_REVIEW = ("Needs Review", 1, 3)
    BLOCKED = ("Blocked", 4, 5)

    def __init__(self, category: str, min_score: int, max_score: int):
        self.category = category
        self.min_score = min_score
        self.max_score = max_score

    @classmethod
    def from_score(cls, score: int) -> "RiskLevel":
        """Determine risk level from a numeric score"""
        for level in cls:
            if level.min_score <= score <= level.max_score:
                return level
        return cls.BLOCKED if score > 3 else cls.SAFE


@dataclass
class OperationRisk:
    type: str
    score: int
    reason: str
    details: dict
    is_policy_violation: bool = False  # True if this is a team policy, not a safety issue
    parent_index: int | None = None  # Index of parent operation if nested (e.g., inside SeparateDatabaseAndState)
    guidance: str | None = None  # How to do this safely if there's a better way

    @property
    def level(self) -> RiskLevel:
        return RiskLevel.from_score(self.score)


@dataclass
class MigrationRisk:
    path: str
    app: str
    name: str
    operations: list[OperationRisk]
    combination_risks: list[str] = field(default_factory=list)
    policy_violations: list[str] = field(default_factory=list)  # PostHog-specific coding policies
    info_messages: list[str] = field(default_factory=list)  # Informational messages (not warnings)

    @property
    def max_score(self) -> int:
        # If there are combination risks or policy violations, boost score to at least 4 (Blocked)
        base_score = max((op.score for op in self.operations), default=0)
        if self.combination_risks or self.policy_violations:
            return max(base_score, 4)
        return base_score

    @property
    def level(self) -> RiskLevel:
        return RiskLevel.from_score(self.max_score)

    @property
    def category(self) -> str:
        return self.level.category
