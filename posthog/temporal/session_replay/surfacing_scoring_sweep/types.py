"""Dataclasses for the surfacing-scoring workflow inputs and outputs.

All payloads are intentionally tiny so they fit comfortably under Temporal's
~2 MiB payload limit. Session IDs and feature vectors never flow through
the workflow — each activity re-queries ClickHouse for its slice using the
deterministic hash partition encoded in `ChunkSpec`.
"""

from dataclasses import dataclass, field


@dataclass
class ScoreSessionsBatchInputs:
    """Top-level workflow input. Empty by design — all sizing is in constants.py.

    A future per-region or per-team variant can extend this without breaking
    existing schedules: extra fields default to None and current scheduler
    logic ignores them.
    """

    pass


@dataclass
class ChunkSpec:
    """Identifies one hash-partitioned slice of unscored sessions.

    `chunk_id` and `of_chunks` define a `cityHash64(session_id) % of_chunks`
    bucket. The activity that receives this re-queries CH for its slice — the
    spec carries no session data, so it's safe to fan out hundreds of these
    in a single workflow without payload pressure.
    """

    chunk_id: int
    of_chunks: int
    chunk_size: int
    lookback_days: int


@dataclass
class ListChunksResult:
    chunks: list[ChunkSpec] = field(default_factory=list)
    estimated_unscored_sessions: int = 0


@dataclass
class ChunkResult:
    chunk_id: int
    # Rows published to Kafka (after dropping out-of-contract rows).
    scored: int = 0
    # Rows the feature SELECT returned from ClickHouse, before any drop.
    fetched: int = 0


@dataclass
class ScoreSessionsBatchResult:
    total_scored: int = 0
    total_fetched: int = 0
    chunks_dispatched: int = 0
    chunks_failed: int = 0
