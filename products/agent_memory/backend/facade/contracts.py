"""Frozen contracts for the agent-memory facade.

These are the only data structures that cross the product boundary. No Django
imports — pure data. See products/architecture.md.
"""

from __future__ import annotations

from datetime import datetime

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class MemoryFile:
    """A single markdown file in a team's memory tree, as returned to callers."""

    path: str
    content: str
    version: int
    updated_by_id: int | None
    updated_by_run: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class MemoryFileSummary:
    """A file's metadata without its (potentially large) body — for listing."""

    path: str
    version: int
    size_bytes: int
    updated_by_run: str | None
    updated_at: datetime
