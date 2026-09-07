"""The resume point of a population operation, and how it is stored."""

from __future__ import annotations

from typing import Any

from posthog.dataclasses import frozen


@frozen
class PopulationProgress:
    """How far an operation has got. Persisted as the operation's ``progress`` JSON column."""

    source_materialized: bool = False
    """The query or filter snapshot is fully in ClickHouse. Set once, never recomputed on retry."""

    chunk_index: int = 0
    """Index of the next input chunk to write. Chunks below it are in both stores."""

    matched: int = 0
    unmatched: int = 0

    sync_cursor: str = "00000000-0000-0000-0000-000000000000"
    """Highest ClickHouse person_id already synchronized to Postgres, for query and filter sources."""

    sync_complete: bool = False
    abandon_sync_started: bool = False

    flag_cursor: int | None = 0
    """Next page cursor for the feature-flag source. ``None`` once the service reports no more pages."""

    pinned_flag_version: int | None = None
    pinned_property_matching_version: int | None = None
    """The flag definition an in-flight run evaluates against, held across retries so a run can
    never mix two definitions of the same flag."""

    def to_json(self) -> dict[str, Any]:
        return {
            "source_materialized": self.source_materialized,
            "chunk_index": self.chunk_index,
            "matched": self.matched,
            "unmatched": self.unmatched,
            "sync_cursor": self.sync_cursor,
            "sync_complete": self.sync_complete,
            "abandon_sync_started": self.abandon_sync_started,
            "flag_cursor": self.flag_cursor,
            "pinned_flag_version": self.pinned_flag_version,
            "pinned_property_matching_version": self.pinned_property_matching_version,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any] | None) -> PopulationProgress:
        """Rebuild from a stored column, ignoring keys an older or newer worker wrote."""
        raw = raw or {}
        defaults = cls()
        return cls(
            source_materialized=bool(raw.get("source_materialized", defaults.source_materialized)),
            chunk_index=int(raw.get("chunk_index", defaults.chunk_index)),
            matched=int(raw.get("matched", defaults.matched)),
            unmatched=int(raw.get("unmatched", defaults.unmatched)),
            sync_cursor=str(raw.get("sync_cursor", defaults.sync_cursor)),
            sync_complete=bool(raw.get("sync_complete", defaults.sync_complete)),
            abandon_sync_started=bool(raw.get("abandon_sync_started", defaults.abandon_sync_started)),
            flag_cursor=raw.get("flag_cursor", defaults.flag_cursor),
            pinned_flag_version=raw.get("pinned_flag_version", defaults.pinned_flag_version),
            pinned_property_matching_version=raw.get(
                "pinned_property_matching_version", defaults.pinned_property_matching_version
            ),
        )
