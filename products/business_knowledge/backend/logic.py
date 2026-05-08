"""
Business logic for business_knowledge.

All ORM access, chunking, quota enforcement, and search queries.
"""

import re
import uuid
from dataclasses import dataclass
from functools import reduce
from operator import or_
from uuid import UUID

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

import structlog

from posthog.security.url_validation import is_url_allowed

from . import crawl, discover, file_parse, html_parse, url_fetch
from .constants import (
    CHUNK_HARD_MAX_CHARS,
    CHUNK_TARGET_CHARS,
    CRAWL_HARD_MAX_DEPTH,
    DEFAULT_CRAWL_MAX_DEPTH,
    DEFAULT_MAX_PAGES,
    MAX_CHUNKS_PER_TEAM,
    MAX_SOURCES_PER_TEAM,
    MAX_TEXT_SIZE_BYTES,
    MAX_URLS_PER_SOURCE,
)
from .models import CrawlMode, KnowledgeChunk, KnowledgeDocument, KnowledgeSource, SourceStatus, SourceType
from .models.constants import RefreshStatus
from .url_fetch import sha256_of

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


def _chunk_id(source_id: UUID, document_stable_id: str, heading_path: str, ordinal: int) -> UUID:
    # `source_id` is in the namespace so two URL-backed sources that happen to
    # crawl the same URL don't collide on chunk UUIDs (document.stable_id == url
    # for URL sources). Text sources already have a uuid4 `stable_id`, but
    # including source_id here keeps the rule uniform.
    return uuid.uuid5(_CHUNK_NAMESPACE, f"{source_id}|{document_stable_id}|{heading_path}|{ordinal}")


def _bulk_create_chunks(
    *,
    source: KnowledgeSource,
    document: KnowledgeDocument,
    team_id: int,
    chunks: list[_Chunk],
) -> None:
    KnowledgeChunk.objects.bulk_create(
        [
            KnowledgeChunk(
                id=_chunk_id(source.id, document.stable_id, c.heading_path, c.ordinal),
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
        return KnowledgeSource.objects.annotate(
            _document_count=Count("documents", distinct=True),
            _chunk_count=Count("chunks", distinct=True),
        ).get(id=source_id, team_id=team_id)
    except KnowledgeSource.DoesNotExist:
        return None


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

    _bulk_create_chunks(source=source, document=document, team_id=team_id, chunks=chunks)

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
        _bulk_create_chunks(source=source, document=document, team_id=team_id, chunks=chunks)
        source.status = SourceStatus.READY
        source.save(update_fields=["status", "updated_at"])
    elif name is not None:
        source.name = name
        source.save(update_fields=["name", "updated_at"])

    return get_for_team(source.id, team_id) or source


def update_url_source(
    *,
    source_id: UUID,
    team_id: int,
    name: str | None = None,
    url: str | None = None,
    crawl_mode: str | None = None,
    crawl_config: dict | None = None,
) -> KnowledgeSource | None:
    """
    Update a URL source's metadata and optionally re-crawl.

    - name-only: single UPDATE, no network.
    - url/crawl_mode/crawl_config change: update the fields, then trigger a
      full refresh so the content matches the new config.
    """
    try:
        source = KnowledgeSource.objects.get(id=source_id, team_id=team_id)
    except KnowledgeSource.DoesNotExist:
        return None
    if source.source_type != SourceType.URL:
        raise InvalidUrlError("Can only update URL sources with this endpoint.")

    needs_recrawl = False
    update_fields: list[str] = ["updated_at"]

    if name is not None and name != source.name:
        source.name = name
        update_fields.append("name")

    if url is not None and url != source.source_url:
        normalized = _validate_url(url)
        source.source_url = normalized
        update_fields.append("source_url")
        needs_recrawl = True

    if crawl_mode is not None and crawl_mode != source.crawl_mode:
        source.crawl_mode = crawl_mode
        update_fields.append("crawl_mode")
        needs_recrawl = True

    if crawl_config is not None:
        merged = {**(source.crawl_config or {}), **crawl_config}
        if merged != source.crawl_config:
            source.crawl_config = merged
            update_fields.append("crawl_config")
            needs_recrawl = True

    if len(update_fields) > 1:
        source.save(update_fields=update_fields)

    if needs_recrawl:
        return refresh_source(source_id=source.id, team_id=team_id)

    return get_for_team(source.id, team_id) or source


@transaction.atomic
def delete_source(source_id: UUID, team_id: int) -> bool:
    deleted, _ = KnowledgeSource.objects.filter(id=source_id, team_id=team_id).delete()
    return deleted > 0


# --- Stage 3: file sources ----------------------------------------------------


def create_file_source(
    *,
    team_id: int,
    created_by_id: int | None,
    name: str,
    file_data: bytes,
    original_filename: str,
) -> KnowledgeSource:
    """
    Stage 3 file ingestion: detect type → parse → chunk. Inline, not Temporal.

    The caller (serializer) already enforced the compressed size cap. This
    function detects the content type from magic bytes, parses the file into
    plain text, chunks it, and persists source + doc + chunks atomically.
    """

    if _count_sources(team_id) >= MAX_SOURCES_PER_TEAM:
        raise QuotaExceededError(f"Team already has {MAX_SOURCES_PER_TEAM} knowledge sources.")

    parsed = file_parse.parse_file(file_data, original_filename)
    text = parsed.content

    if len(text.encode("utf-8")) > MAX_TEXT_SIZE_BYTES:
        raise file_parse.FileTooLargeError(
            f"Parsed content exceeds the {MAX_TEXT_SIZE_BYTES // (1024 * 1024)} MB text cap. "
            "Try a shorter document or split it into multiple sources."
        )

    chunks = chunk_text(text)
    content_hash = sha256_of(text)

    with transaction.atomic():
        source = KnowledgeSource.objects.create(
            team_id=team_id,
            created_by_id=created_by_id,
            name=name,
            source_type=SourceType.FILE,
            status=SourceStatus.PROCESSING,
            original_filename=file_parse.sanitize_filename(original_filename),
            file_content_type=parsed.content_type,
            file_size_bytes=len(file_data),
        )

        if _count_chunks(team_id) + len(chunks) > MAX_CHUNKS_PER_TEAM:
            raise QuotaExceededError("File produces more chunks than the remaining team budget.")

        document_id = uuid.uuid4()
        document = KnowledgeDocument.objects.create(
            id=document_id,
            team_id=team_id,
            source=source,
            stable_id=str(document_id),
            title=parsed.title,
            content=text,
            metadata=parsed.metadata,
            content_hash=content_hash,
        )

        _bulk_create_chunks(source=source, document=document, team_id=team_id, chunks=chunks)

        source.status = SourceStatus.READY
        source.save(update_fields=["status", "updated_at"])

    return get_for_team(source.id, team_id) or source


# --- Stage 2a: URL sources ---------------------------------------------------


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


def _resolve_crawl_config(raw: dict | None) -> discover.CrawlConfig:
    """
    Turn a stored/user-supplied dict into a validated `CrawlConfig`. Applies
    hard caps defensively — we don't trust stored values not to drift past
    caps when the caps get lowered.
    """

    raw = raw or {}
    max_pages = int(raw.get("max_pages", DEFAULT_MAX_PAGES))
    max_pages = max(1, min(max_pages, MAX_URLS_PER_SOURCE))
    max_depth = int(raw.get("max_depth", DEFAULT_CRAWL_MAX_DEPTH))
    max_depth = max(0, min(max_depth, CRAWL_HARD_MAX_DEPTH))
    return discover.CrawlConfig(
        include_globs=tuple(raw.get("include_globs", []) or []),
        exclude_globs=tuple(raw.get("exclude_globs", []) or []),
        max_depth=max_depth,
        max_pages=max_pages,
    )


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
    _bulk_create_chunks(source=source, document=document, team_id=team_id, chunks=chunks)


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
        # Create the source in ERROR state so the user can see it, retry via
        # refresh, or delete it. Returning 201 with an error-state source is
        # better UX than a 400 that orphans a row the client has no ID for.
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
        return get_for_team(source.id, team_id) or source

    content_hash = sha256_of(text)
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

    Dispatches on `crawl_mode`:
      - `single` (Stage 2a): single-URL conditional GET + full doc rebuild.
      - `sitemap` / `same_origin` (Stage 2b): re-discover + per-URL upsert.
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

    if source.crawl_mode and source.crawl_mode != CrawlMode.SINGLE:
        return _refresh_crawl_source(source=source, team_id=team_id)
    return _refresh_single_source(source=source, team_id=team_id)


def _refresh_single_source(*, source: KnowledgeSource, team_id: int) -> KnowledgeSource | None:
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

    new_hash = sha256_of(text)
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


# --- Stage 2b: crawl sources -------------------------------------------------


def _insert_document_and_chunks(
    *,
    source: KnowledgeSource,
    team_id: int,
    title: str,
    text: str,
    url: str,
    etag: str,
    content_hash: str,
    existing_doc: KnowledgeDocument | None,
) -> int:
    """
    Upsert a single document (and its chunks) under a crawl source.

    `existing_doc` is the doc for this URL on the source, if any. When
    present, we preserve its `id` so agent citations stay stable across
    refreshes — the chunks get wiped and regenerated.

    Returns the number of chunks written.
    """

    chunks = chunk_text(text)

    if existing_doc is None:
        document = KnowledgeDocument.objects.create(
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
    else:
        document = existing_doc
        document.title = title or document.title or source.name
        document.content = text
        document.metadata = {**(document.metadata or {}), "source_type": SourceType.URL, "url": url}
        document.url = url
        document.etag = etag
        document.content_hash = content_hash
        document.tombstoned_at = None
        document.save(
            update_fields=[
                "title",
                "content",
                "metadata",
                "url",
                "etag",
                "content_hash",
                "tombstoned_at",
                "updated_at",
            ]
        )
        # Wipe stale chunks before re-inserting — simpler than diffing
        # chunk-by-chunk and the chunker is deterministic for stable text.
        KnowledgeChunk.objects.filter(team_id=team_id, document_id=document.id).delete()

    _bulk_create_chunks(source=source, document=document, team_id=team_id, chunks=chunks)
    return len(chunks)


def create_crawl_source(
    *,
    team_id: int,
    created_by_id: int | None,
    name: str,
    url: str,
    crawl_mode: str,
    crawl_config: dict | None,
) -> KnowledgeSource:
    """
    Stage 2b multi-URL ingestion.

    Happy path:
      1. Validate + normalize the entry URL (same SSRF plumbing as Stage 2a).
      2. Discover candidate URLs via sitemap / same-origin BFS.
      3. Fetch all candidates in parallel with a per-host semaphore.
      4. In a single transaction, create the source row and bulk-insert
         one document + N chunks per successfully fetched URL.

    A crawl that discovers zero URLs lands a source in ERROR status so the
    user can see the failure and either adjust globs or retry. A crawl
    that discovers URLs but fetches none successfully also lands in ERROR.
    """

    if crawl_mode == CrawlMode.SINGLE:
        # Shouldn't happen — the serializer dispatches `single` to
        # create_url_source. Be defensive though.
        return create_url_source(team_id=team_id, created_by_id=created_by_id, name=name, url=url)

    check_url_source_quota(team_id)
    normalized = _validate_url(url)
    config = _resolve_crawl_config(crawl_config)

    # Step 1: discover. Failures here abort the create — we never persist
    # a source we couldn't even start on.
    try:
        candidate_urls = discover.discover(crawl_mode, normalized, config)
    except discover.DiscoverError as exc:
        raise UrlFetchFailedError(str(exc)) from exc

    if not candidate_urls:
        raise EmptyContentError("Crawl discovered no URLs. Check the entry URL and globs.")

    # Step 2: parallel fetch. Re-validate every URL before the fetch — a
    # malicious sitemap could point at `file://` or `127.0.0.1`.
    safe_urls: list[str] = []
    for u in candidate_urls:
        try:
            safe_urls.append(_validate_url(u))
        except InvalidUrlError:
            logger.info("business_knowledge.crawl.ssrf_skipped", source_url=normalized, skipped=u)
            continue

    if not safe_urls:
        raise EmptyContentError("Crawl discovered no safe URLs to fetch.")

    outcomes = crawl.fetch_many(safe_urls)
    ok_outcomes = [o for o in outcomes if o.status == "ok"]

    if not ok_outcomes:
        now = timezone.now()
        first_error = next((o.error for o in outcomes if o.status == "error"), "All pages failed to fetch.")
        with transaction.atomic():
            source = KnowledgeSource.objects.create(
                team_id=team_id,
                created_by_id=created_by_id,
                name=name,
                source_type=SourceType.URL,
                status=SourceStatus.ERROR,
                error_message=first_error,
                source_url=normalized,
                crawl_mode=crawl_mode,
                crawl_config=crawl_config or {},
                last_refresh_at=now,
                last_refresh_status=RefreshStatus.ERROR,
                last_refresh_error=first_error,
            )
        return get_for_team(source.id, team_id) or source

    # Pre-chunk budget estimate. We still do the post-insert exact check
    # inside the transaction.
    estimated_total = sum(max(1, len(o.text) // CHUNK_TARGET_CHARS) for o in ok_outcomes)
    if _count_chunks(team_id) + estimated_total > MAX_CHUNKS_PER_TEAM:
        raise QuotaExceededError(f"Crawl would exceed the {MAX_CHUNKS_PER_TEAM} chunk cap.")

    # Step 3: atomic create.
    with transaction.atomic():
        source = KnowledgeSource.objects.create(
            team_id=team_id,
            created_by_id=created_by_id,
            name=name,
            source_type=SourceType.URL,
            status=SourceStatus.PROCESSING,
            source_url=normalized,
            crawl_mode=crawl_mode,
            crawl_config=crawl_config or {},
        )
        total_chunks_written = 0
        for outcome in ok_outcomes:
            written = _insert_document_and_chunks(
                source=source,
                team_id=team_id,
                title=outcome.title,
                text=outcome.text,
                url=outcome.url,
                etag=outcome.etag,
                content_hash=outcome.content_hash,
                existing_doc=None,
            )
            total_chunks_written += written

        # Exact post-insert quota check. Rolls back the whole txn if we blew
        # past the cap — no partial crawl persists.
        if _count_chunks(team_id) > MAX_CHUNKS_PER_TEAM:
            raise QuotaExceededError(f"Crawl exceeded the {MAX_CHUNKS_PER_TEAM} chunk cap.")

        source.status = SourceStatus.READY
        source.last_refresh_at = timezone.now()
        source.last_refresh_status = RefreshStatus.SUCCESS
        source.last_refresh_error = ""
        source.save(
            update_fields=[
                "status",
                "last_refresh_at",
                "last_refresh_status",
                "last_refresh_error",
                "updated_at",
            ]
        )

    return get_for_team(source.id, team_id) or source


def _refresh_crawl_source(*, source: KnowledgeSource, team_id: int) -> KnowledgeSource | None:
    """
    Stage 2b crawl refresh: re-discover + per-URL upsert-diff.

    - New URL → insert document + chunks.
    - Existing URL with changed `content_hash` → rebuild that doc's chunks
      (document row id preserved for citation stability).
    - Existing URL with unchanged hash → no DB writes.
    - Existing URL that vanished from discovery → mark tombstoned_at,
      delete chunks (keep the doc row so a later re-appearance can reuse
      the id). Stage 5 adds a sweep that hard-deletes after 7 days.
    """

    try:
        config = _resolve_crawl_config(source.crawl_config)
        normalized = _validate_url(source.source_url)
        try:
            discovered = discover.discover(source.crawl_mode, normalized, config)
        except discover.DiscoverError as exc:
            raise UrlFetchFailedError(str(exc)) from exc
    except (InvalidUrlError, UrlFetchFailedError) as exc:
        with transaction.atomic():
            fresh = KnowledgeSource.objects.get(id=source.id, team_id=team_id)
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

    # Load existing docs keyed by stable_id (== url). Pulling all of them up
    # front is cheap (we're capped at MAX_URLS_PER_SOURCE) and avoids a
    # per-URL query inside the fetch loop.
    existing_by_url: dict[str, KnowledgeDocument] = {
        d.stable_id: d for d in KnowledgeDocument.objects.filter(team_id=team_id, source_id=source.id)
    }

    # Pre-SSRF the discovered list and preserve ETags per URL for conditional GETs.
    safe_urls: list[str] = []
    for u in discovered:
        try:
            safe_urls.append(_validate_url(u))
        except InvalidUrlError:
            continue

    def _etag_for(u: str) -> str | None:
        existing = existing_by_url.get(u)
        return existing.etag if existing and existing.etag else None

    outcomes = crawl.fetch_many(safe_urls, etag_for=_etag_for)
    # `discovered_set` is built by normalizing the raw discovered URLs (lowercased
    # scheme+host, no fragment) so keys match `existing_by_url` (which uses the
    # normalized stable_id). We do NOT use `safe_urls` here — that would tombstone
    # URLs that transiently fail SSRF re-validation even though the sitemap still
    # lists them.
    discovered_set: set[str] = set()
    for u in discovered:
        try:
            discovered_set.add(url_fetch.normalize_url(u))
        except url_fetch.UrlFetchError:
            pass

    with transaction.atomic():
        fresh = KnowledgeSource.objects.select_for_update().get(id=source.id, team_id=team_id)

        # Upsert per-outcome.
        any_changes = False
        for outcome in outcomes:
            existing = existing_by_url.get(outcome.url)
            if outcome.status == "not_modified":
                # Still touch the etag so a rotation stays fresh.
                if existing and outcome.etag and existing.etag != outcome.etag:
                    existing.etag = outcome.etag
                    existing.save(update_fields=["etag", "updated_at"])
                continue
            if outcome.status == "error":
                # Keep the old doc intact — partial failures shouldn't
                # knock out a previously-working page.
                logger.info(
                    "business_knowledge.crawl.refresh_page_error",
                    source_id=str(source.id),
                    url=outcome.url,
                    error=outcome.error,
                )
                continue
            assert outcome.status == "ok"
            if existing is not None and existing.content_hash == outcome.content_hash:
                # No re-chunk needed. Still bump etag if we got a new one.
                if outcome.etag and existing.etag != outcome.etag:
                    existing.etag = outcome.etag
                    existing.save(update_fields=["etag", "updated_at"])
                continue
            _insert_document_and_chunks(
                source=fresh,
                team_id=team_id,
                title=outcome.title,
                text=outcome.text,
                url=outcome.url,
                etag=outcome.etag,
                content_hash=outcome.content_hash,
                existing_doc=existing,
            )
            any_changes = True

        # Tombstone docs whose URL vanished from discovery. Chunks go away
        # now; the sweep in Stage 5 hard-deletes the doc row after a grace
        # period (preserves the id in case the page comes back soon).
        vanished = [d for url, d in existing_by_url.items() if url not in discovered_set]
        if vanished:
            now = timezone.now()
            vanished_ids = [d.id for d in vanished]
            KnowledgeChunk.objects.filter(team_id=team_id, document_id__in=vanished_ids).delete()
            KnowledgeDocument.objects.filter(team_id=team_id, id__in=vanished_ids, tombstoned_at__isnull=True).update(
                tombstoned_at=now, updated_at=now
            )
            any_changes = True

        # Exact post-diff quota check.
        if _count_chunks(team_id) > MAX_CHUNKS_PER_TEAM:
            raise QuotaExceededError(f"Refresh exceeded the {MAX_CHUNKS_PER_TEAM} chunk cap.")

        fresh.status = SourceStatus.READY
        fresh.last_refresh_at = timezone.now()
        fresh.last_refresh_status = RefreshStatus.SUCCESS if any_changes else RefreshStatus.NOT_MODIFIED
        fresh.last_refresh_error = ""
        fresh.error_message = ""
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

    return get_for_team(source.id, team_id) or fresh


# ---------------------------------------------------------------------------
# AI agent read-path
# ---------------------------------------------------------------------------


def has_ready_sources(team_id: int) -> bool:
    """True when the team has at least one READY source (READY implies chunks exist)."""
    return KnowledgeSource.objects.filter(team_id=team_id, status=SourceStatus.READY).exists()


_SEARCH_LIMIT_CAP = 20

_WORD_RE = re.compile(r"\w{2,}", re.UNICODE)


@dataclass(frozen=True)
class KnowledgeSearchResult:
    """A single chunk returned by a knowledge search, with source context."""

    chunk_id: UUID
    source_id: UUID
    source_name: str
    source_type: str
    document_title: str
    heading_path: str
    ordinal: int
    content: str


def search_knowledge(
    team_id: int,
    query: str,
    *,
    limit: int = 10,
) -> list[KnowledgeSearchResult]:
    """
    Word-level ILIKE search over chunks belonging to READY sources.

    Splits the query into words (>=2 chars) and matches chunks containing
    ANY of them (OR). Uses the GIN trigram index for performance. Results
    are ordered by char_count ascending (shorter, more focused chunks first).
    """
    limit = max(1, min(limit, _SEARCH_LIMIT_CAP))

    words = _WORD_RE.findall(query)
    if not words:
        return []

    word_filters = reduce(or_, (Q(content__icontains=w) for w in words))

    chunks = (
        KnowledgeChunk.objects.filter(
            word_filters,
            team_id=team_id,
            source__status=SourceStatus.READY,
            document__tombstoned_at__isnull=True,
        )
        .select_related("source", "document")
        .only(
            "id",
            "source_id",
            "document_id",
            "heading_path",
            "ordinal",
            "content",
            "source__name",
            "source__source_type",
            "document__title",
        )
        .order_by("char_count")[:limit]
    )

    return [
        KnowledgeSearchResult(
            chunk_id=c.id,
            source_id=c.source_id,
            source_name=c.source.name,
            source_type=c.source.source_type,
            document_title=c.document.title,
            heading_path=c.heading_path,
            ordinal=c.ordinal,
            content=c.content,
        )
        for c in chunks
    ]
