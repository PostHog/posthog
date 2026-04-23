"""Exported enums and quota constants for business_knowledge."""

from enum import StrEnum


class SourceType(StrEnum):
    TEXT = "text"
    URL = "url"
    FILE = "file"


class SourceStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"


# Per-team caps. Enforced in the create endpoint, not at the DB layer — easier
# to relax for a single paying customer without a migration.
MAX_SOURCES_PER_TEAM = 500
MAX_CHUNKS_PER_TEAM = 100_000
# 1 MB of raw text. Above this Stage 1 refuses the create; for longer docs the
# customer is expected to split them or wait for Stage 2/3.
MAX_TEXT_SIZE_BYTES = 1_000_000

# Chunker tunables. Kept here (not in logic.py) so the retrieval eval harness
# can import them without pulling Django.
CHUNK_TARGET_CHARS = 1200
CHUNK_HARD_MAX_CHARS = 1600
