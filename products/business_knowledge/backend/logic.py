"""
Business logic for business_knowledge.

All ORM access, chunking, quota enforcement. Only facade/api.py is allowed
to call into this module.
"""

import uuid
from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.db.models import Count

from .facade.enums import (
    CHUNK_HARD_MAX_CHARS,
    CHUNK_TARGET_CHARS,
    MAX_CHUNKS_PER_TEAM,
    MAX_SOURCES_PER_TEAM,
    MAX_TEXT_SIZE_BYTES,
)
from .models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource, SourceStatus, SourceType

# Deterministic namespace for chunk uuid5. Rolling this breaks id stability
# across Stage 1 data — so don't. Generated once via uuid.uuid4() and frozen.
_CHUNK_NAMESPACE = UUID("4b7b0b50-5e2f-4a9f-8a8b-8b8d5f6f4a3e")


class QuotaExceededError(Exception):
    """Raised when creating the source would exceed a per-team cap."""


class TextTooLargeError(Exception):
    """Raw text exceeds MAX_TEXT_SIZE_BYTES."""


@dataclass(frozen=True)
class _Chunk:
    heading_path: str
    ordinal: int
    content: str


# --- Chunker -----------------------------------------------------------------


def chunk_text(text: str) -> list[_Chunk]:
    """
    Paragraph-aware chunker for Stage 1 plain text.

    Strategy:
    - Split on blank lines (paragraph boundary).
    - Greedily pack paragraphs into buckets up to CHUNK_TARGET_CHARS.
    - If a single paragraph blows past CHUNK_HARD_MAX_CHARS, split it on
      whitespace near the boundary (best-effort, no sentence tokenizer —
      we stay dependency-free on purpose).

    No overlap between chunks. Agent search reads neighbors via ordinal
    ± 1 when it wants wider context; overlap would just bloat storage.
    """

    paragraphs = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    buckets: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            buckets.append(current)
            current = ""

    for paragraph in paragraphs:
        # Hard-split any mega paragraph before we try to pack it.
        while len(paragraph) > CHUNK_HARD_MAX_CHARS:
            cut = paragraph.rfind(" ", 0, CHUNK_HARD_MAX_CHARS)
            if cut <= 0:
                cut = CHUNK_HARD_MAX_CHARS
            head, paragraph = paragraph[:cut].rstrip(), paragraph[cut:].lstrip()
            if current:
                flush()
            buckets.append(head)

        if not current:
            current = paragraph
        elif len(current) + len(paragraph) + 2 <= CHUNK_TARGET_CHARS:
            current = f"{current}\n\n{paragraph}"
        else:
            flush()
            current = paragraph

    flush()

    return [_Chunk(heading_path="", ordinal=i, content=c) for i, c in enumerate(buckets)]


def _chunk_id(document_stable_id: str, heading_path: str, ordinal: int) -> UUID:
    return uuid.uuid5(_CHUNK_NAMESPACE, f"{document_stable_id}|{heading_path}|{ordinal}")


# --- Quota enforcement -------------------------------------------------------


def _count_sources(team_id: int) -> int:
    return KnowledgeSource.objects.filter(team_id=team_id).count()


def _count_chunks(team_id: int) -> int:
    return KnowledgeChunk.objects.filter(team_id=team_id).count()


def check_text_source_quota(team_id: int, text: str) -> None:
    if len(text.encode("utf-8")) > MAX_TEXT_SIZE_BYTES:
        raise TextTooLargeError(f"Text exceeds {MAX_TEXT_SIZE_BYTES} bytes. Split it into multiple sources.")
    if _count_sources(team_id) >= MAX_SOURCES_PER_TEAM:
        raise QuotaExceededError(f"Team already has {MAX_SOURCES_PER_TEAM} knowledge sources.")
    # We can't know exact chunk count before chunking, but we can cheaply
    # estimate and fail fast. The strict check happens post-chunk inside the
    # transaction.
    estimated_chunks = max(1, len(text) // CHUNK_TARGET_CHARS)
    if _count_chunks(team_id) + estimated_chunks > MAX_CHUNKS_PER_TEAM:
        raise QuotaExceededError(f"Team already near the {MAX_CHUNKS_PER_TEAM} chunk cap.")


# --- Queries -----------------------------------------------------------------


def list_for_team(team_id: int) -> list[KnowledgeSource]:
    # Annotate counts in one round-trip so the serializer doesn't N+1.
    return list(
        KnowledgeSource.objects.filter(team_id=team_id)
        .annotate(
            _document_count=Count("documents", distinct=True),
            _chunk_count=Count("chunks", distinct=True),
        )
        .order_by("-created_at")
    )


def get_for_team(source_id: UUID, team_id: int) -> KnowledgeSource | None:
    try:
        return (
            KnowledgeSource.objects.filter(team_id=team_id)
            .annotate(
                _document_count=Count("documents", distinct=True),
                _chunk_count=Count("chunks", distinct=True),
            )
            .get(id=source_id)
        )
    except KnowledgeSource.DoesNotExist:
        return None


def count_ready_sources_for_team(team_id: int) -> int:
    return KnowledgeSource.objects.filter(team_id=team_id, status=SourceStatus.READY).count()


def list_ready_source_names_for_team(team_id: int, limit: int = 20) -> list[str]:
    return list(
        KnowledgeSource.objects.filter(team_id=team_id, status=SourceStatus.READY)
        .order_by("-created_at")
        .values_list("name", flat=True)[:limit]
    )


def list_chunks_for_source(source_id: UUID, team_id: int, limit: int = 50) -> list[KnowledgeChunk]:
    return list(
        KnowledgeChunk.objects.filter(team_id=team_id, source_id=source_id)
        .select_related("document")
        .order_by("document_id", "ordinal")[:limit]
    )


# --- Mutations ---------------------------------------------------------------


@transaction.atomic
def create_text_source(
    *,
    team_id: int,
    created_by_id: int | None,
    name: str,
    text: str,
) -> KnowledgeSource:
    """
    Stage 1 happy path: create source + 1 document + N chunks synchronously.

    Inline, not Temporal. Text parsing is pure CPU and quick; adding a
    workflow for every text paste burns latency for zero gain.
    """

    check_text_source_quota(team_id, text)

    source = KnowledgeSource.objects.create(
        team_id=team_id,
        created_by_id=created_by_id,
        name=name,
        source_type=SourceType.TEXT,
        status=SourceStatus.PROCESSING,
    )

    # One text source == one document. Stable_id is the document's own UUID,
    # which means re-saving the same text to a new source gets a fresh stable_id
    # (that's intentional — two sources with identical text are two logical
    # entries, not a dedup target).
    document_id = uuid.uuid4()
    document = KnowledgeDocument.objects.create(
        id=document_id,
        team_id=team_id,
        source=source,
        stable_id=str(document_id),
        title=name,
        content=text,
        metadata={"source_type": SourceType.TEXT},
    )

    chunks = chunk_text(text)
    if _count_chunks(team_id) + len(chunks) > MAX_CHUNKS_PER_TEAM:
        # Roll back — transaction will undo source + document.
        raise QuotaExceededError(f"Text produces more chunks than the remaining team budget.")

    KnowledgeChunk.objects.bulk_create(
        [
            KnowledgeChunk(
                id=_chunk_id(document.stable_id, c.heading_path, c.ordinal),
                team_id=team_id,
                source=source,
                document=document,
                heading_path=c.heading_path,
                ordinal=c.ordinal,
                content=c.content,
                char_count=len(c.content),
            )
            for c in chunks
        ]
    )

    source.status = SourceStatus.READY
    source.save(update_fields=["status", "updated_at"])
    # Refresh annotations so the returned instance has accurate counts.
    return get_for_team(source.id, team_id) or source


@transaction.atomic
def delete_source(source_id: UUID, team_id: int) -> bool:
    deleted, _ = KnowledgeSource.objects.filter(id=source_id, team_id=team_id).delete()
    return deleted > 0
