"""Detector protocol + analysis context.

A ``Detector`` is a single subclass with a class-level ``name`` and ``run``
that yields ``Finding`` objects from an ``AnalysisContext``. Add new
detectors by writing a new module under ``detectors/`` and appending the
class to ``runner.DEFAULT_DETECTORS``.

Detectors should be:
- **Pure** — no side effects, no DB access.
- **Defensive** — return an empty iterable rather than raising. The runner
  catches exceptions but uncaught exceptions are still noise.
- **Cheap** — the timeline indexes are pre-built; lookups should be O(1)
  per finding.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from posthog.management.migration_profiling.dead_code.models import Finding
from posthog.management.migration_profiling.dead_code.parser import ParsedMigration
from posthog.management.migration_profiling.dead_code.timeline import Timeline


@dataclass
class AnalysisContext:
    """Everything a detector needs in one place.

    ``profile_ops`` is the loaded JSONL data (one dict per op record), if
    available. Detectors that don't need it can ignore it.
    """

    timeline: Timeline
    migrations: list[ParsedMigration]
    migrations_by_app_name: dict[tuple[str, str], ParsedMigration]
    profile_ops: list[dict[str, Any]]


class Detector(ABC):
    """Subclass and implement ``run``. Set ``name`` + ``description`` on the class."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        """Yield findings produced from the context."""
        ...
