"""
Business logic for business_knowledge.

All ORM access, chunking, quota enforcement. Only facade/api.py is allowed
to call into this module.
"""

import uuid
import hashlib
from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

import structlog

from posthog.security.url_validation import is_url_allowed

from . import html_parse, url_fetch
from .facade.enums import (
    CHUNK_HARD_MAX_CHARS,
    CHUNK_TARGET_CHARS,
    MAX_CHUNKS_PER_TEAM,
    MAX_SOURCES_PER_TEAM,
    MAX_TEXT_SIZE_BYTES,
)
from .models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource, SourceStatus, SourceType
from .models.constants import RefreshStatus

logger = structlog.get_logger(__name__)

# Deterministic namespace for chunk uuid5. Rolling this breaks id stability
# across Stage 1 data — so don't. Generated once via uuid.uuid4() and frozen.
_CHUNK_NAMESPACE = UUID("4b7b0b50-5e2f-4a9f-8a8b-8b8d5f6f4a3e")


class QuotaExceededError(Exception):
    """Raised when creating the source would exceed a per-team cap."""


class TextTooLargeError(Exception):
    """Raw text exceeds MAX_TEXT_SIZE_BYTES."""


class InvalidUrlError(Exception):
    """URL failed SSRF or basic validation. Message is user-safe."""


class UrlFetchFailedError(Exception):
    """Fetch or parse failed. Message is user-safe (never includes server detail)."""


class SourceBusyError(Exception):
    """A refresh is already running for this source."""


class EmptyContentError(Exception):
    """Remote returned nothing usable after parsing."""


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


def get_source_text_for_team(source_id: UUID, team_id: int) -> str | None:
    """
    Returns the raw text of a text-type source. Stage 1 has exactly one
    document per source, so this is a single row fetch. For future URL/file
    sources with many documents, this concatenates in stable order — not a
    real "view" affordance but good enough to round-trip into the edit modal.
    """

    if not KnowledgeSource.objects.filter(id=source_id, team_id=team_id).exists():
        return None
    documents = KnowledgeDocument.objects.filter(team_id=team_id, source_id=source_id).order_by("created_at")
    return "\n\n".join(d.content for d in documents)


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
def update_text_source(
    *,
    source_id: UUID,
    team_id: int,
    name: str | None,
    text: str | None,
) -> KnowledgeSource | None:
    """
    Stage 1 edit path.

    - name-only edit: single UPDATE, no re-chunk.
    - text edit: delete documents+chunks for this source and rebuild from the
      new content. We keep the source row (and its id) so agents' in-flight
      prompts don't go stale on re-lookup. Same byte/chunk quota rules apply
      to the new text.

    Returns the refreshed source (with annotated counts) or None if the
    source doesn't belong to this team.
    """

    try:
        source = KnowledgeSource.objects.get(id=source_id, team_id=team_id)
    except KnowledgeSource.DoesNotExist:
        return None

    if text is not None:
        if len(text.encode("utf-8")) > MAX_TEXT_SIZE_BYTES:
            raise TextTooLargeError(f"Text exceeds {MAX_TEXT_SIZE_BYTES} bytes.")
        chunks = chunk_text(text)
        # Post-chunk budget check. Existing chunks for this source are about to
        # be deleted, so subtract them before comparing to the cap.
        existing_chunks_for_source = KnowledgeChunk.objects.filter(team_id=team_id, source_id=source_id).count()
        if _count_chunks(team_id) - existing_chunks_for_source + len(chunks) > MAX_CHUNKS_PER_TEAM:
            raise QuotaExceededError(f"Team already near the {MAX_CHUNKS_PER_TEAM} chunk cap.")

        source.status = SourceStatus.PROCESSING
        update_fields = ["status", "updated_at"]
        if name is not None:
            source.name = name
            update_fields.append("name")
        source.save(update_fields=update_fields)

        KnowledgeChunk.objects.filter(team_id=team_id, source_id=source_id).delete()
        KnowledgeDocument.objects.filter(team_id=team_id, source_id=source_id).delete()

        document_id = uuid.uuid4()
        document = KnowledgeDocument.objects.create(
            id=document_id,
            team_id=team_id,
            source=source,
            stable_id=str(document_id),
            title=name if name is not None else source.name,
            content=text,
            metadata={"source_type": SourceType.TEXT},
        )
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
    elif name is not None:
        source.name = name
        source.save(update_fields=["name", "updated_at"])

    return get_for_team(source.id, team_id) or source


@transaction.atomic
def delete_source(source_id: UUID, team_id: int) -> bool:
    deleted, _ = KnowledgeSource.objects.filter(id=source_id, team_id=team_id).delete()
    return deleted > 0


# --- Stage 2a: URL sources ---------------------------------------------------


def _sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_url(url: str) -> str:
    """Normalize + SSRF check. Raises InvalidUrlError on failure."""

    try:
        normalized = url_fetch.normalize_url(url)
    except url_fetch.UrlFetchError:
        raise InvalidUrlError("Invalid URL.")
    allowed, _reason = is_url_allowed(normalized)
    if not allowed:
        raise InvalidUrlError("URL is not reachable from this environment.")
    return normalized


def check_url_source_quota(team_id: int) -> None:
    """
    Byte/chunk caps are enforced post-fetch (we don't know the body size until
    we've fetched). Here we only short-circuit the per-team source count.
    """

    if _count_sources(team_id) >= MAX_SOURCES_PER_TEAM:
        raise QuotaExceededError(f"Team already has {MAX_SOURCES_PER_TEAM} knowledge sources.")


def _fetch_and_parse(url: str, *, etag: str | None) -> tuple[url_fetch.FetchResult, str, str]:
    """
    Fetch + parse for create/refresh paths. Returns (fetch_result, title, text).
    Raises UrlFetchFailedError / EmptyContentError on bad input.

    On 304 returns empty (title, text) — caller must check fetch.status first.
    """

    try:
        result = url_fetch.fetch_url(url, etag=etag)
    except url_fetch.UrlFetchError as exc:
        raise UrlFetchFailedError(str(exc))

    if result.status == 304:
        return result, "", ""

    if not result.body:
        raise EmptyContentError("Remote response was empty.")

    if not url_fetch.is_html_content_type(result.content_type):
        raise UrlFetchFailedError("Unsupported content type.")

    title, text = html_parse.parse_html(result.body, result.final_url)
    if not text.strip():
        raise EmptyContentError("Could not extract any text from the URL.")
    if len(text.encode("utf-8")) > MAX_TEXT_SIZE_BYTES:
        # Trim rather than refuse — a 2MB Wikipedia page is still useful.
        # Cut on a character boundary within the byte budget.
        raise UrlFetchFailedError("URL content exceeds the maximum allowed size.")
    return result, title, text


def _replace_source_content(
    *,
    source: KnowledgeSource,
    team_id: int,
    title: str,
    text: str,
    url: str,
    etag: str,
    content_hash: str,
) -> None:
    """
    Delete existing documents+chunks for `source` and create a fresh 1-doc/
    N-chunk set from the given text. Must be called inside a transaction.

    The chunk count budget is enforced here (after we already know the exact
    count). Existing chunks for this source are subtracted before comparison.
    """

    chunks = chunk_text(text)
    existing_chunks_for_source = KnowledgeChunk.objects.filter(team_id=team_id, source_id=source.id).count()
    if _count_chunks(team_id) - existing_chunks_for_source + len(chunks) > MAX_CHUNKS_PER_TEAM:
        raise QuotaExceededError(f"Team already near the {MAX_CHUNKS_PER_TEAM} chunk cap.")

    KnowledgeChunk.objects.filter(team_id=team_id, source_id=source.id).delete()
    KnowledgeDocument.objects.filter(team_id=team_id, source_id=source.id).delete()

    document_id = uuid.uuid4()
    # stable_id = normalized URL so Stage 2b crawls can upsert by (source, url)
    # and a re-fetch of the same URL keeps the same identity — helps agents
    # that cache by document id across refreshes.
    document = KnowledgeDocument.objects.create(
        id=document_id,
        team_id=team_id,
        source=source,
        stable_id=url,
        title=title or source.name,
        content=text,
        metadata={"source_type": SourceType.URL, "url": url},
        url=url,
        etag=etag,
        content_hash=content_hash,
    )
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


def create_url_source(
    *,
    team_id: int,
    created_by_id: int | None,
    name: str,
    url: str,
) -> KnowledgeSource:
    """
    Stage 2a URL ingestion: validate → fetch → parse → chunk.

    Fetch happens *before* the DB transaction so a 10s HTTP call doesn't hold
    a row-level write lock. The source row is then created atomically with
    its documents and chunks.
    """

    check_url_source_quota(team_id)
    normalized = _validate_url(url)

    try:
        result, title, text = _fetch_and_parse(normalized, etag=None)
    except (UrlFetchFailedError, EmptyContentError) as exc:
        # Create the source in ERROR state so the user can see what happened
        # and retry via refresh. Keeping it visible is better UX than a
        # silent 4xx that vanishes.
        with transaction.atomic():
            now = timezone.now()
            source = KnowledgeSource.objects.create(
                team_id=team_id,
                created_by_id=created_by_id,
                name=name,
                source_type=SourceType.URL,
                status=SourceStatus.ERROR,
                error_message=str(exc),
                source_url=normalized,
                last_refresh_at=now,
                last_refresh_status=RefreshStatus.ERROR,
                last_refresh_error=str(exc),
            )
        raise UrlFetchFailedError(str(exc)) from exc

    content_hash = _sha256_of(text)
    with transaction.atomic():
        source = KnowledgeSource.objects.create(
            team_id=team_id,
            created_by_id=created_by_id,
            name=name,
            source_type=SourceType.URL,
            status=SourceStatus.PROCESSING,
            source_url=normalized,
        )
        _replace_source_content(
            source=source,
            team_id=team_id,
            title=title,
            text=text,
            url=result.final_url,
            etag=result.etag or "",
            content_hash=content_hash,
        )
        source.status = SourceStatus.READY
        source.last_refresh_at = timezone.now()
        source.last_refresh_status = RefreshStatus.SUCCESS
        source.last_refresh_error = ""
        source.last_etag = result.etag or ""
        source.save(
            update_fields=[
                "status",
                "last_refresh_at",
                "last_refresh_status",
                "last_refresh_error",
                "last_etag",
                "updated_at",
            ]
        )

    return get_for_team(source.id, team_id) or source


def refresh_source(*, source_id: UUID, team_id: int) -> KnowledgeSource | None:
    """
    Re-fetch a URL source and rebuild its content if it changed.

    Uses `If-None-Match` with the last-seen ETag for cheap 304 short-circuits.
    On 200 we compare `content_hash(parsed_text)` before re-chunking — avoids
    churn when a template change leaves the visible text identical.

    The DB transaction is held only while mutating rows; the HTTP fetch is
    outside the txn to keep lock windows small.
    """

    # Pull the source once outside the txn just to verify it exists + claim it.
    with transaction.atomic():
        try:
            source = KnowledgeSource.objects.select_for_update(skip_locked=True).get(id=source_id, team_id=team_id)
        except KnowledgeSource.DoesNotExist:
            return None
        if source.source_type != SourceType.URL or not source.source_url:
            raise InvalidUrlError("Only URL sources can be refreshed.")
        if source.status == SourceStatus.PROCESSING:
            raise SourceBusyError("This source is already refreshing.")
        source.status = SourceStatus.PROCESSING
        source.save(update_fields=["status", "updated_at"])

    try:
        # Re-validate the URL before every fetch — we don't assume stored URLs
        # are still safe (DNS may have been rebound since create time).
        normalized = _validate_url(source.source_url)
        result, title, text = _fetch_and_parse(normalized, etag=source.last_etag or None)
    except (InvalidUrlError, UrlFetchFailedError, EmptyContentError) as exc:
        with transaction.atomic():
            fresh = KnowledgeSource.objects.get(id=source.id, team_id=team_id)
            # Leave existing chunks intact so queries keep working even while
            # refresh is broken — that's why last_refresh_status is separate.
            fresh.status = SourceStatus.READY if fresh.documents.exists() else SourceStatus.ERROR
            fresh.last_refresh_at = timezone.now()
            fresh.last_refresh_status = RefreshStatus.ERROR
            fresh.last_refresh_error = str(exc)
            if fresh.status == SourceStatus.ERROR:
                fresh.error_message = str(exc)
            fresh.save(
                update_fields=[
                    "status",
                    "last_refresh_at",
                    "last_refresh_status",
                    "last_refresh_error",
                    "error_message",
                    "updated_at",
                ]
            )
        raise

    if result.status == 304:
        with transaction.atomic():
            fresh = KnowledgeSource.objects.get(id=source.id, team_id=team_id)
            fresh.status = SourceStatus.READY
            fresh.last_refresh_at = timezone.now()
            fresh.last_refresh_status = RefreshStatus.NOT_MODIFIED
            fresh.last_refresh_error = ""
            # ETag occasionally rotates without content changes; store whatever
            # the server sent (or keep the previous one if absent).
            if result.etag:
                fresh.last_etag = result.etag
            fresh.save(
                update_fields=[
                    "status",
                    "last_refresh_at",
                    "last_refresh_status",
                    "last_refresh_error",
                    "last_etag",
                    "updated_at",
                ]
            )
        return get_for_team(source.id, team_id) or fresh

    new_hash = _sha256_of(text)
    with transaction.atomic():
        fresh = KnowledgeSource.objects.select_for_update().get(id=source.id, team_id=team_id)
        existing_doc = (
            KnowledgeDocument.objects.filter(team_id=team_id, source_id=fresh.id).order_by("created_at").first()
        )
        content_changed = existing_doc is None or existing_doc.content_hash != new_hash
        if content_changed:
            _replace_source_content(
                source=fresh,
                team_id=team_id,
                title=title,
                text=text,
                url=result.final_url,
                etag=result.etag or "",
                content_hash=new_hash,
            )
        fresh.status = SourceStatus.READY
        fresh.last_refresh_at = timezone.now()
        # Distinct status from "no content change" — NOT_MODIFIED means
        # "server told us 304". If content hash matches despite a 200, we still
        # classify as SUCCESS (a refresh happened; it just produced no diff).
        fresh.last_refresh_status = RefreshStatus.SUCCESS
        fresh.last_refresh_error = ""
        fresh.last_etag = result.etag or ""
        fresh.error_message = ""
        fresh.save(
            update_fields=[
                "status",
                "last_refresh_at",
                "last_refresh_status",
                "last_refresh_error",
                "last_etag",
                "error_message",
                "updated_at",
            ]
        )

    return get_for_team(source.id, team_id) or fresh
