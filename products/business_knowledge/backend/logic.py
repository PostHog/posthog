"""
Business logic for business_knowledge.

All ORM access, chunking, quota enforcement, and search queries.
"""

import uuid
import datetime
from dataclasses import dataclass
from functools import reduce
from operator import or_
from urllib.parse import urlsplit
from uuid import UUID

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db import (
    connection as db_connection,
    transaction,
)
from django.db.models import Count, Exists, F, OuterRef, Q
from django.db.models.functions import Substr
from django.utils import timezone

import structlog

from posthog.helpers.full_text_search import process_query
from posthog.models.scoping import with_team_scope
from posthog.security.url_validation import is_url_allowed

from . import crawl, discover, file_parse, html_parse, url_fetch
from .constants import (
    CHUNK_HARD_MAX_CHARS,
    CHUNK_TARGET_CHARS,
    CLASSIFY_MAX_ATTEMPTS,
    CLASSIFY_MAX_TOTAL_CHARS,
    CRAWL_HARD_MAX_DEPTH,
    DEFAULT_CRAWL_MAX_DEPTH,
    DEFAULT_MAX_PAGES,
    MAX_CHUNKS_PER_TEAM,
    MAX_SOURCES_PER_TEAM,
    MAX_TEXT_SIZE_BYTES,
    MAX_URLS_PER_SOURCE,
)
from .models import (
    REFRESH_INTERVAL_TIMEDELTAS,
    CrawlMode,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    RefreshInterval,
    SafetyVerdict,
    SourceStatus,
    SourceType,
)
from .models.constants import RefreshStatus
from .url_fetch import sha256_of

logger = structlog.get_logger(__name__)

# Deterministic namespace for chunk uuid5. Rolling this breaks id stability
# across data — so don't. Generated once via uuid.uuid4() and frozen.
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
    Paragraph-aware chunker.

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
    created = KnowledgeChunk.objects.bulk_create(
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
    # Populate the FTS vector here (the single chunk-creation choke point) so it
    # stays correct everywhere — including the test schema, which is built from
    # model state with migrations disabled and so would never run a DB trigger.
    # Computed in Postgres via `to_tsvector('english', content)`.
    if created:
        KnowledgeChunk.objects.filter(id__in=[c.id for c in created]).update(
            content_search_vector=SearchVector("content", config="english")
        )


# --- Quota enforcement -------------------------------------------------------


def _count_sources(team_id: int) -> int:
    return KnowledgeSource.objects.filter(team_id=team_id).count()


# Advisory-lock namespace so we don't collide with other lock users.
# pg_advisory_xact_lock takes a bigint; we combine a fixed namespace
# with team_id to get a unique key per team.
_ADVISORY_LOCK_NAMESPACE = 0x424B  # "BK" for business_knowledge


def _acquire_source_quota_lock(team_id: int) -> None:
    """
    Acquire a transaction-scoped Postgres advisory lock keyed on team_id.

    Must be called inside ``transaction.atomic()``. The lock is released
    automatically when the transaction commits or rolls back.

    This serializes concurrent source-create transactions for the same
    team, closing the READ COMMITTED phantom-read window that lets two
    concurrent creates both see ``count=499`` and both insert.
    """
    lock_id = (_ADVISORY_LOCK_NAMESPACE << 32) | (team_id & 0xFFFFFFFF)
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_id])


def _check_source_quota_locked(team_id: int, *, reject_if_processing: bool = False) -> None:
    """
    Acquire the advisory lock, then check the source count.
    Must be inside a transaction.

    When *reject_if_processing* is True, also enforces the per-team
    concurrency invariant (at most one PROCESSING source) under the
    same lock — closing the TOCTOU window between concurrent creates.

    Stale PROCESSING rows (older than ``_PROCESSING_STALENESS_MINUTES``)
    are auto-recovered to ERROR before the check so a crashed request
    doesn't permanently block new creates.
    """
    _acquire_source_quota_lock(team_id)
    if reject_if_processing:
        stale_cutoff = timezone.now() - datetime.timedelta(minutes=_PROCESSING_STALENESS_MINUTES)
        KnowledgeSource.objects.filter(
            team_id=team_id,
            status=SourceStatus.PROCESSING,
            updated_at__lt=stale_cutoff,
        ).update(
            status=SourceStatus.ERROR,
            error_message="Processing timed out. You can retry via refresh.",
        )
        if KnowledgeSource.objects.filter(team_id=team_id, status=SourceStatus.PROCESSING).exists():
            raise SourceBusyError("Another knowledge source is already being processed for this project.")
    if _count_sources(team_id) >= MAX_SOURCES_PER_TEAM:
        raise QuotaExceededError(f"Team already has {MAX_SOURCES_PER_TEAM} knowledge sources.")


def _count_chunks(team_id: int) -> int:
    return KnowledgeChunk.objects.filter(team_id=team_id).count()


@with_team_scope(canonical=True)
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


def _unsafe_documents_subquery() -> Exists:
    return Exists(
        KnowledgeDocument.objects.filter(
            source_id=OuterRef("pk"),
            safety_verdict=SafetyVerdict.UNSAFE,
            tombstoned_at__isnull=True,
        )
    )


@with_team_scope(canonical=True)
def list_for_team(team_id: int) -> list[KnowledgeSource]:
    # Annotate counts in one round-trip so the serializer doesn't N+1.
    return list(
        KnowledgeSource.objects.filter(team_id=team_id)
        .annotate(
            _document_count=Count("documents", distinct=True),
            _chunk_count=Count("chunks", distinct=True),
            _has_unsafe_documents=_unsafe_documents_subquery(),
        )
        .order_by("-created_at")
    )


@with_team_scope(canonical=True)
def get_for_team(source_id: UUID, team_id: int) -> KnowledgeSource | None:
    try:
        return KnowledgeSource.objects.annotate(
            _document_count=Count("documents", distinct=True),
            _chunk_count=Count("chunks", distinct=True),
            _has_unsafe_documents=_unsafe_documents_subquery(),
        ).get(id=source_id, team_id=team_id)
    except KnowledgeSource.DoesNotExist:
        return None


@with_team_scope(canonical=True)
def get_source_text_for_team(source_id: UUID, team_id: int) -> str | None:
    """
    Returns the raw text of a text-type source. Has exactly one
    document per source, so this is a single row fetch. For future URL/file
    sources with many documents, this concatenates in stable order — not a
    real "view" affordance but good enough to round-trip into the edit modal.
    """

    if not KnowledgeSource.objects.filter(id=source_id, team_id=team_id).exists():
        return None
    documents = KnowledgeDocument.objects.filter(team_id=team_id, source_id=source_id).order_by("created_at")
    return "\n\n".join(d.content for d in documents)


# --- Mutations ---------------------------------------------------------------


@with_team_scope(canonical=True)
@transaction.atomic
def create_text_source(
    *,
    team_id: int,
    created_by_id: int | None,
    name: str,
    text: str,
) -> KnowledgeSource:
    """
    Create source + 1 document + N chunks synchronously.

    Inline, not Temporal. Text parsing is pure CPU and quick; adding a
    workflow for every text paste burns latency for zero gain.
    """

    check_text_source_quota(team_id, text)

    _check_source_quota_locked(team_id)
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
        content_hash=sha256_of(text),
        # Pasted text is still untrusted *content* — a member who can add a
        # source could paste prompt-injection text and have the agent surface
        # it verbatim (search only filters `safety_verdict=SAFE`). The classifier
        # is the security boundary for everything agent-searchable, so leave the
        # doc `unknown` (excluded) until the coordinator clears it, same as
        # URL/crawl/file docs. content_hash is the version token the verdict
        # write is matched against (see set_document_safety).
        safety_verdict=SafetyVerdict.UNKNOWN,
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


@with_team_scope(canonical=True)
@transaction.atomic
def update_text_source(
    *,
    source_id: UUID,
    team_id: int,
    name: str | None,
    text: str | None,
) -> KnowledgeSource | None:
    """
    Edit path.

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
            content_hash=sha256_of(text),
            # Edited text is re-classified before it can resurface — see the
            # rationale in create_text_source. Delete+recreate gives a fresh id,
            # so there's no stale-verdict race here; content_hash still scopes
            # the eventual verdict write to exactly this content.
            safety_verdict=SafetyVerdict.UNKNOWN,
        )
        _bulk_create_chunks(source=source, document=document, team_id=team_id, chunks=chunks)
        source.status = SourceStatus.READY
        source.save(update_fields=["status", "updated_at"])
    elif name is not None:
        source.name = name
        source.save(update_fields=["name", "updated_at"])

    return get_for_team(source.id, team_id) or source


@with_team_scope(canonical=True)
def update_url_source(
    *,
    source_id: UUID,
    team_id: int,
    name: str | None = None,
    url: str | None = None,
    crawl_mode: str | None = None,
    crawl_config: dict | None = None,
    refresh_interval: str | None = None,
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
    old_values: dict[str, object] = {}

    if name is not None and name != source.name:
        source.name = name
        update_fields.append("name")

    # Cadence change is metadata-only — never forces a re-crawl.
    if refresh_interval is not None and refresh_interval != source.refresh_interval:
        source.refresh_interval = refresh_interval
        update_fields.append("refresh_interval")

    if url is not None and url != source.source_url:
        normalized = _validate_url(url)
        old_values["source_url"] = source.source_url
        source.source_url = normalized
        update_fields.append("source_url")
        needs_recrawl = True

    if crawl_mode is not None and crawl_mode != source.crawl_mode:
        old_values["crawl_mode"] = source.crawl_mode
        source.crawl_mode = crawl_mode
        update_fields.append("crawl_mode")
        needs_recrawl = True

    if crawl_config is not None:
        merged = {**(source.crawl_config or {}), **crawl_config}
        if merged != source.crawl_config:
            old_values["crawl_config"] = source.crawl_config
            source.crawl_config = merged
            update_fields.append("crawl_config")
            needs_recrawl = True

    if len(update_fields) > 1:
        source.save(update_fields=update_fields)

    if needs_recrawl:
        try:
            return refresh_source(source_id=source.id, team_id=team_id)
        except SourceBusyError:
            # Refresh never started — revert config so the source doesn't
            # end up with a new URL but old content and no error signal.
            for field, value in old_values.items():
                setattr(source, field, value)
            source.save(update_fields=[*list(old_values.keys()), "updated_at"])
            raise

    return get_for_team(source.id, team_id) or source


@with_team_scope(canonical=True)
@transaction.atomic
def delete_source(source_id: UUID, team_id: int) -> bool:
    try:
        source = KnowledgeSource.objects.get(id=source_id, team_id=team_id)
    except KnowledgeSource.DoesNotExist:
        return False
    source.delete()
    return True


# --- File sources ------------------------------------------------------------


@with_team_scope(canonical=True)
def create_file_source(
    *,
    team_id: int,
    created_by_id: int | None,
    name: str,
    file_data: bytes,
    original_filename: str,
) -> KnowledgeSource:
    """
    Detect type → parse → chunk. Inline, not Temporal.

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
        _check_source_quota_locked(team_id)
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
            # Files are opaque: a member can upload a PDF/DOCX they merely
            # downloaded, with hidden/embedded prompt-injection text they never
            # saw. That's "trusted user, untrusted content" — so leave the doc
            # `unknown` (excluded from agent search) until the coordinator's
            # classifier clears it, exactly like URL/crawl docs. Only pasted
            # text (which the member typed and can see) is trusted SAFE inline.
            safety_verdict=SafetyVerdict.UNKNOWN,
        )

        _bulk_create_chunks(source=source, document=document, team_id=team_id, chunks=chunks)

        source.status = SourceStatus.READY
        source.save(update_fields=["status", "updated_at"])

    return get_for_team(source.id, team_id) or source


# --- URL sources -------------------------------------------------------------


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


_PROCESSING_STALENESS_MINUTES = 10


def _resolve_crawl_config(raw: dict | None) -> discover.CrawlConfig:
    """
    Turn a stored/user-supplied dict into a validated ``CrawlConfig``. Applies
    hard caps defensively — we don't trust stored values not to drift past
    caps when the caps get lowered.

    All conversions are wrapped in try/except so corrupt JSON (e.g. from
    a manual admin edit) falls back to safe defaults instead of 500-ing.
    """

    if not isinstance(raw, dict):
        raw = {}
    else:
        raw = raw or {}
    try:
        max_pages = int(raw.get("max_pages", DEFAULT_MAX_PAGES))
    except (TypeError, ValueError):
        max_pages = DEFAULT_MAX_PAGES
    max_pages = max(1, min(max_pages, MAX_URLS_PER_SOURCE))

    try:
        max_depth = int(raw.get("max_depth", DEFAULT_CRAWL_MAX_DEPTH))
    except (TypeError, ValueError):
        max_depth = DEFAULT_CRAWL_MAX_DEPTH
    max_depth = max(0, min(max_depth, CRAWL_HARD_MAX_DEPTH))

    include_raw = raw.get("include_globs") or []
    exclude_raw = raw.get("exclude_globs") or []
    include_globs = tuple(str(g) for g in include_raw if isinstance(g, str))
    exclude_globs = tuple(str(g) for g in exclude_raw if isinstance(g, str))

    return discover.CrawlConfig(
        include_globs=include_globs,
        exclude_globs=exclude_globs,
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
    # stable_id = normalized URL so crawls can upsert by (source, url)
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


@with_team_scope(canonical=True)
def claim_url_source(
    *,
    team_id: int,
    created_by_id: int | None,
    name: str,
    url: str,
    crawl_mode: str | None = None,
    crawl_config: dict | None = None,
    refresh_interval: str | None = None,
) -> KnowledgeSource:
    """
    Create the PROCESSING claim row for a URL/crawl source *without* fetching.

    Returns immediately so the request can respond and a background worker
    (`ingest_source`) fills the content. URL normalization + SSRF validation
    still happen here so a bad URL is a synchronous 400, and the advisory lock
    + PROCESSING-state check still serialize concurrent creates per team.
    """

    normalized = _validate_url(url)

    with transaction.atomic():
        _check_source_quota_locked(team_id, reject_if_processing=True)
        source = KnowledgeSource.objects.create(
            team_id=team_id,
            created_by_id=created_by_id,
            name=name,
            source_type=SourceType.URL,
            status=SourceStatus.PROCESSING,
            source_url=normalized,
            crawl_mode=crawl_mode or CrawlMode.SINGLE,
            crawl_config=crawl_config or {},
            refresh_interval=refresh_interval or RefreshInterval.MANUAL,
        )
    return source


def _ingest_url_source(*, source: KnowledgeSource, team_id: int) -> KnowledgeSource | None:
    """
    Fetch + parse + chunk a single-URL source that's already claimed PROCESSING.

    Extracted from the old inline create so the same path runs both inline and
    in a background Temporal activity. Re-validates the URL (DNS may have been
    rebound between claim and fetch) and records failures on the row.
    """

    try:
        normalized = _validate_url(source.source_url)
        result, title, text = _fetch_and_parse(normalized, etag=None)
    except (InvalidUrlError, UrlFetchFailedError, EmptyContentError) as exc:
        with transaction.atomic():
            fresh = KnowledgeSource.objects.get(id=source.id, team_id=team_id)
            now = timezone.now()
            fresh.status = SourceStatus.ERROR
            fresh.error_message = str(exc)
            fresh.last_refresh_at = now
            fresh.last_refresh_status = RefreshStatus.ERROR
            fresh.last_refresh_error = str(exc)
            fresh.save(
                update_fields=[
                    "status",
                    "error_message",
                    "last_refresh_at",
                    "last_refresh_status",
                    "last_refresh_error",
                    "updated_at",
                ]
            )
        return get_for_team(source.id, team_id) or source

    content_hash = sha256_of(text)
    try:
        with transaction.atomic():
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
    except QuotaExceededError:
        with transaction.atomic():
            fresh = KnowledgeSource.objects.get(id=source.id, team_id=team_id)
            fresh.status = SourceStatus.ERROR
            fresh.error_message = "Quota exceeded"
            fresh.last_refresh_at = timezone.now()
            fresh.last_refresh_status = RefreshStatus.ERROR
            fresh.last_refresh_error = "Quota exceeded"
            fresh.save(
                update_fields=[
                    "status",
                    "error_message",
                    "last_refresh_at",
                    "last_refresh_status",
                    "last_refresh_error",
                    "updated_at",
                ]
            )
        raise

    return get_for_team(source.id, team_id) or source


@with_team_scope(canonical=True)
def create_url_source(
    *,
    team_id: int,
    created_by_id: int | None,
    name: str,
    url: str,
) -> KnowledgeSource:
    """
    Synchronous single-URL ingestion: claim → fetch → parse → chunk.

    Kept for callers/tests that want the result inline; the API create path
    instead claims and hands ingestion to a background worker.
    """
    source = claim_url_source(team_id=team_id, created_by_id=created_by_id, name=name, url=url)
    return _ingest_url_source(source=source, team_id=team_id) or source


@with_team_scope(canonical=True)
def ingest_source(*, source_id: UUID, team_id: int) -> KnowledgeSource | None:
    """
    Background ingestion entry point for a freshly-claimed PROCESSING source.

    Dispatches on `crawl_mode` and reuses the same `_ingest_*` bodies as the
    synchronous create path, so create semantics (empty crawl = error, etc.)
    are identical. Called from the Temporal ingest activity and as an inline
    fallback when the workflow can't be started.
    """
    try:
        source = KnowledgeSource.objects.get(id=source_id, team_id=team_id)
    except KnowledgeSource.DoesNotExist:
        return None
    if source.source_type != SourceType.URL or not source.source_url:
        return source
    if source.crawl_mode and source.crawl_mode != CrawlMode.SINGLE:
        return _ingest_crawl_source(source=source, team_id=team_id)
    return _ingest_url_source(source=source, team_id=team_id)


@with_team_scope(canonical=True)
def claim_refresh_source(*, source_id: UUID, team_id: int) -> KnowledgeSource:
    """
    Mark a URL source PROCESSING so a background worker can refresh it.

    Acquires the per-team advisory lock and enforces the single-PROCESSING
    invariant. Raises `SourceBusyError` / `InvalidUrlError` synchronously so
    the API can return 409 / 400 before kicking off the workflow.
    """
    with transaction.atomic():
        _check_source_quota_locked(team_id, reject_if_processing=True)
        try:
            source = KnowledgeSource.objects.select_for_update().get(id=source_id, team_id=team_id)
        except KnowledgeSource.DoesNotExist:
            raise
        if source.source_type != SourceType.URL or not source.source_url:
            raise InvalidUrlError("Only URL sources can be refreshed.")
        if source.status == SourceStatus.PROCESSING:
            raise SourceBusyError("This source is already refreshing.")
        source.status = SourceStatus.PROCESSING
        source.save(update_fields=["status", "updated_at"])
    return source


@with_team_scope(canonical=True)
def execute_refresh_source(*, source_id: UUID, team_id: int) -> KnowledgeSource | None:
    """
    Actually re-fetch + rebuild a source that's already claimed PROCESSING.

    Called from a Temporal activity or as an inline fallback. The claim must
    have happened beforehand via `claim_refresh_source`.
    """
    try:
        source = KnowledgeSource.objects.get(id=source_id, team_id=team_id)
    except KnowledgeSource.DoesNotExist:
        return None

    try:
        if source.crawl_mode and source.crawl_mode != CrawlMode.SINGLE:
            return _refresh_crawl_source(source=source, team_id=team_id)
        return _refresh_single_source(source=source, team_id=team_id)
    except QuotaExceededError:
        with transaction.atomic():
            fresh = KnowledgeSource.objects.get(id=source.id, team_id=team_id)
            fresh.status = SourceStatus.READY if fresh.documents.exists() else SourceStatus.ERROR
            fresh.last_refresh_at = timezone.now()
            fresh.last_refresh_status = RefreshStatus.ERROR
            fresh.last_refresh_error = "Quota exceeded"
            if fresh.status == SourceStatus.ERROR:
                fresh.error_message = "Quota exceeded"
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


@with_team_scope(canonical=True)
def refresh_source(*, source_id: UUID, team_id: int) -> KnowledgeSource | None:
    """
    Synchronous claim + refresh. Used by the background coordinator activity
    and kept for callers/tests that want the result inline.
    """
    try:
        claim_refresh_source(source_id=source_id, team_id=team_id)
    except KnowledgeSource.DoesNotExist:
        return None
    return execute_refresh_source(source_id=source_id, team_id=team_id)


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


# --- Crawl sources -----------------------------------------------------------


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
        # Content changed (caller only reaches this branch on a hash diff), so
        # the prior safety verdict no longer applies — re-queue for
        # classification with a fresh attempt budget.
        document.safety_verdict = SafetyVerdict.UNKNOWN
        document.safety_reason = ""
        document.classification_attempts = 0
        document.save(
            update_fields=[
                "title",
                "content",
                "metadata",
                "url",
                "etag",
                "content_hash",
                "tombstoned_at",
                "safety_verdict",
                "safety_reason",
                "classification_attempts",
                "updated_at",
            ]
        )
        # Wipe stale chunks before re-inserting — simpler than diffing
        # chunk-by-chunk and the chunker is deterministic for stable text.
        KnowledgeChunk.objects.filter(team_id=team_id, document_id=document.id).delete()

    _bulk_create_chunks(source=source, document=document, team_id=team_id, chunks=chunks)
    return len(chunks)


@with_team_scope(canonical=True)
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
    Multi-URL ingestion.

    Happy path:
      1. Validate + normalize the entry URL (same SSRF plumbing).
      2. Claim a PROCESSING row under advisory lock so concurrent creates
         for the same team are serialized.
      3. Discover candidate URLs via sitemap / same-origin BFS.
      4. Fetch all candidates in parallel with a per-host semaphore.
      5. In a transaction, bulk-insert documents + chunks and mark READY.

    Failures at any stage update the claim row to ERROR so the user can
    see the failure, adjust globs, or retry.
    """

    if crawl_mode == CrawlMode.SINGLE:
        return create_url_source(team_id=team_id, created_by_id=created_by_id, name=name, url=url)

    source = claim_url_source(
        team_id=team_id,
        created_by_id=created_by_id,
        name=name,
        url=url,
        crawl_mode=crawl_mode,
        crawl_config=crawl_config,
    )
    return _ingest_crawl_source(source=source, team_id=team_id) or source


def _ingest_crawl_source(*, source: KnowledgeSource, team_id: int) -> KnowledgeSource | None:
    """
    Discover + fetch + chunk a multi-URL source that's already claimed
    PROCESSING. Extracted from the old inline create so the same path runs
    both inline and in a background Temporal activity.

    Unlike `_refresh_crawl_source`, an empty discovery is an *error* here —
    a brand-new source that indexed nothing should surface that, whereas a
    refresh that finds nothing keeps the existing content.
    """

    config = _resolve_crawl_config(source.crawl_config)

    def _mark_error(error_msg: str) -> KnowledgeSource:
        with transaction.atomic():
            fresh = KnowledgeSource.objects.get(id=source.id, team_id=team_id)
            now = timezone.now()
            fresh.status = SourceStatus.ERROR
            fresh.error_message = error_msg
            fresh.last_refresh_at = now
            fresh.last_refresh_status = RefreshStatus.ERROR
            fresh.last_refresh_error = error_msg
            fresh.save(
                update_fields=[
                    "status",
                    "error_message",
                    "last_refresh_at",
                    "last_refresh_status",
                    "last_refresh_error",
                    "updated_at",
                ]
            )
        return get_for_team(source.id, team_id) or source

    try:
        # Re-validate the entry URL (DNS may have rebound between claim and ingest).
        normalized = _validate_url(source.source_url)
    except InvalidUrlError as exc:
        return _mark_error(str(exc))

    try:
        candidate_urls = discover.discover(source.crawl_mode, normalized, config)
    except discover.DiscoverError as exc:
        return _mark_error(str(exc))

    if not candidate_urls:
        return _mark_error("Crawl discovered no URLs. Check the entry URL and globs.")

    safe_urls: list[str] = []
    for u in candidate_urls:
        try:
            safe_urls.append(_validate_url(u))
        except InvalidUrlError:
            logger.info("business_knowledge.crawl.ssrf_skipped", source_url=normalized, skipped=u)
            continue

    if not safe_urls:
        return _mark_error("Crawl discovered no safe URLs to fetch.")

    outcomes = crawl.fetch_many(safe_urls)
    ok_outcomes = [o for o in outcomes if o.status == "ok"]

    if not ok_outcomes:
        first_error = next((o.error for o in outcomes if o.status == "error"), "All pages failed to fetch.")
        return _mark_error(first_error)

    estimated_total = sum(max(1, len(o.text) // CHUNK_TARGET_CHARS) for o in ok_outcomes)
    if _count_chunks(team_id) + estimated_total > MAX_CHUNKS_PER_TEAM:
        return _mark_error(f"Crawl would exceed the {MAX_CHUNKS_PER_TEAM} chunk cap.")

    try:
        with transaction.atomic():
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
    except QuotaExceededError:
        _mark_error(f"Crawl exceeded the {MAX_CHUNKS_PER_TEAM} chunk cap.")
        raise

    return get_for_team(source.id, team_id) or source


def _refresh_crawl_source(*, source: KnowledgeSource, team_id: int) -> KnowledgeSource | None:
    """
    Crawl refresh: re-discover + per-URL upsert-diff.

    - New URL → insert document + chunks.
    - Existing URL with changed `content_hash` → rebuild that doc's chunks
      (document row id preserved for citation stability).
    - Existing URL with unchanged hash → no DB writes.
    - Existing URL that vanished from discovery → mark tombstoned_at,
      delete chunks (keep the doc row so a later re-appearance can reuse
      the id).
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
        # now; the sweep hard-deletes the doc row after a grace
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


@with_team_scope(canonical=True)
def has_ready_sources(team_id: int) -> bool:
    """True when the team has at least one READY source (READY implies chunks exist)."""
    return KnowledgeSource.objects.filter(team_id=team_id, status=SourceStatus.READY).exists()


_SEARCH_LIMIT_CAP = 20


@dataclass(frozen=True)
class KnowledgeSearchResult:
    """A single chunk returned by a knowledge search, with source context."""

    chunk_id: UUID
    source_id: UUID
    source_name: str
    source_type: str
    document_id: UUID
    document_title: str
    heading_path: str
    ordinal: int
    content: str


@with_team_scope(canonical=True)
def search_knowledge(
    team_id: int,
    query: str,
    *,
    limit: int = 10,
) -> list[KnowledgeSearchResult]:
    """
    Full-text relevance search over chunks belonging to READY sources.

    Builds an `english`-config `tsquery` from the user query (stemming +
    stopword removal + prefix match on the last term, via `process_query`) with
    OR semantics, and matches it against the chunk `content_search_vector` using
    the GIN index. The top `limit` matches by `ts_rank` (so chunks hitting more
    query terms rank first) anchor the result; each anchor is expanded to its
    ordinal-adjacent neighbours (ordinal n-1, n, n+1 within the same document)
    so the agent gets continuous context instead of isolated fragments.
    `ordinal` is document-global and contiguous, so neighbours never cross into
    a different document.
    """
    limit = max(1, min(limit, _SEARCH_LIMIT_CAP))

    # `process_query` strips tsquery metacharacters and joins terms with a
    # trailing prefix match; returns None when the query is empty / all
    # stopwords-punctuation, in which case there is nothing to search for.
    processed = process_query(query)
    if processed is None:
        return []
    # OR rather than AND the terms: the agent sends natural-language questions,
    # and AND drops any chunk missing a single term (e.g. "can a customer get a
    # refund within 30 days" wouldn't match a focused refund chunk). `ts_rank`
    # still surfaces chunks matching more terms first. `process_query` only ever
    # inserts " & " as a separator, so the replace is unambiguous.
    processed = processed.replace(" & ", " | ")
    search_query = SearchQuery(processed, config="english", search_type="raw")

    anchors = list(
        KnowledgeChunk.objects.filter(
            team_id=team_id,
            source__status=SourceStatus.READY,
            document__tombstoned_at__isnull=True,
            document__safety_verdict=SafetyVerdict.SAFE,
            content_search_vector=search_query,
        )
        .annotate(rank=SearchRank(F("content_search_vector"), search_query))
        .only("id", "document_id", "ordinal", "char_count")
        # `id` is the final tiebreaker so rank+length ties order deterministically.
        .order_by("-rank", "char_count", "id")[:limit]
    )
    if not anchors:
        return []

    # Preserve relevance ranking at the document level (first anchor wins) and
    # collect the ordinal window we want to fetch for each document.
    doc_rank: dict[UUID, int] = {}
    wanted_ordinals: dict[UUID, set[int]] = {}
    for rank, anchor in enumerate(anchors):
        doc_rank.setdefault(anchor.document_id, rank)
        wanted_ordinals.setdefault(anchor.document_id, set()).update(
            (anchor.ordinal - 1, anchor.ordinal, anchor.ordinal + 1)
        )

    window_filter = reduce(
        or_,
        (Q(document_id=doc_id, ordinal__in=sorted(ords)) for doc_id, ords in wanted_ordinals.items()),
    )

    chunks = (
        KnowledgeChunk.objects.filter(
            window_filter,
            team_id=team_id,
            source__status=SourceStatus.READY,
            document__tombstoned_at__isnull=True,
            document__safety_verdict=SafetyVerdict.SAFE,
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
    )

    # Order by document relevance, then ordinal so neighbours stay contiguous.
    ordered = sorted(chunks, key=lambda c: (doc_rank.get(c.document_id, len(anchors)), c.ordinal))

    return [
        KnowledgeSearchResult(
            chunk_id=c.id,
            source_id=c.source_id,
            source_name=c.source.name,
            source_type=c.source.source_type,
            document_id=c.document_id,
            document_title=c.document.title,
            heading_path=c.heading_path,
            ordinal=c.ordinal,
            content=c.content,
        )
        for c in ordered
    ]


# ---------------------------------------------------------------------------
# Background-refresh coordinator helpers (cross-team)
#
# These run inside Temporal activities — never request handlers — so they
# deliberately scan across teams via `.unscoped()`. Each returns plain data
# (ids, strings, ints) so nothing heavy crosses the Temporal boundary.
# ---------------------------------------------------------------------------

# Bound how much one coordinator pass touches so a large backlog can't blow up
# a single workflow run; the hourly cadence drains the rest on later passes.
DUE_SOURCES_SCAN_CAP = 500
# Kept deliberately small: each pending doc now carries up to
# CLASSIFY_MAX_TOTAL_CHARS (~1 MB) of content so the classifier can inspect the
# WHOLE searchable span (not just a 12 KB prefix). At 50 that's ~50 MB resident
# in the activity worst case; raising it scales memory linearly.
PENDING_CLASSIFICATION_SCAN_CAP = 50


@dataclass(frozen=True)
class PendingDocument:
    """A document awaiting safety classification."""

    team_id: int
    document_id: UUID
    content: str
    # Version token of `content` at the moment it was read for classification.
    # The verdict write is gated on this still matching, so a concurrent refresh
    # that swaps the content (crawl upsert keeps the same document_id) can't
    # have a stale verdict applied to the new content. See `set_document_safety`.
    content_hash: str


def list_due_refresh_sources(
    *,
    now: datetime.datetime | None = None,
    limit: int = DUE_SOURCES_SCAN_CAP,
) -> list[tuple[int, UUID, str]]:
    """
    Return ``(team_id, source_id, host)`` for URL sources whose refresh is due.

    Due = a non-``manual`` ``refresh_interval`` AND (never refreshed OR
    ``last_refresh_at`` older than that interval). PROCESSING sources are
    skipped (a refresh is already running). Cross-team — coordinator only.

    ``host`` is the source URL's hostname (``""`` if unparseable); the
    coordinator uses it to avoid hitting one origin from several refreshes at
    once (the per-crawl semaphore only bounds a single source's fetches).
    """
    now = now or timezone.now()
    due: list[tuple[int, UUID, str]] = []
    for interval, delta in REFRESH_INTERVAL_TIMEDELTAS.items():
        remaining = limit - len(due)
        if remaining <= 0:
            break
        cutoff = now - delta
        rows = (
            KnowledgeSource.objects.unscoped()
            .filter(source_type=SourceType.URL, refresh_interval=interval)
            .exclude(status=SourceStatus.PROCESSING)
            .filter(Q(last_refresh_at__isnull=True) | Q(last_refresh_at__lte=cutoff))
            .values_list("team_id", "id", "source_url")[:remaining]
        )
        due.extend((team_id, source_id, urlsplit(url or "").hostname or "") for team_id, source_id, url in rows)
    return due


def list_documents_pending_classification(
    *,
    limit: int = PENDING_CLASSIFICATION_SCAN_CAP,
) -> list[PendingDocument]:
    """
    Return documents whose ``safety_verdict`` is still ``unknown``.

    Only live (non-tombstoned) docs are worth classifying. Cross-team —
    coordinator only. New / content-changed docs are the only ones that reach
    ``unknown``, so classification cost stays linear with changes.

    Docs are only returned for orgs that approved AI data processing — we must
    not send their content to an LLM otherwise. Non-approved orgs' docs stay
    ``unknown`` (and therefore excluded from search — fail closed).

    Docs that have already burned ``CLASSIFY_MAX_ATTEMPTS`` passes without a
    verdict are skipped: the classifier fails closed, so they stay ``unknown``
    (excluded) but we stop re-queuing them so a permanently-unclassifiable doc
    (e.g. content that always trips the model's own safety filter) can't loop
    forever.
    """
    # The classifier inspects the whole document, but we cap how much we pull
    # into memory per doc at CLASSIFY_MAX_TOTAL_CHARS + 1 — the classifier
    # fails closed on anything longer than the cap, and the +1 lets it detect
    # that the content was truncated here without a second Length() round-trip.
    rows = (
        KnowledgeDocument.objects.unscoped()
        .filter(
            safety_verdict=SafetyVerdict.UNKNOWN,
            tombstoned_at__isnull=True,
            classification_attempts__lt=CLASSIFY_MAX_ATTEMPTS,
            team__organization__is_ai_data_processing_approved=True,
        )
        .annotate(content_capped=Substr("content", 1, CLASSIFY_MAX_TOTAL_CHARS + 1))
        .values_list("team_id", "id", "content_capped", "content_hash")[:limit]
    )
    return [
        PendingDocument(team_id=team_id, document_id=doc_id, content=content, content_hash=content_hash)
        for team_id, doc_id, content, content_hash in rows
    ]


@with_team_scope(canonical=True)
def set_document_safety(*, team_id: int, document_id: UUID, verdict: str, content_hash: str, reason: str = "") -> None:
    """
    Persist a classifier outcome on a single document (team-scoped write).

    A definitive ``safe`` / ``unsafe`` verdict is stored and the attempt
    counter reset. An ``unknown`` outcome means the classifier could not get a
    trustworthy verdict (model block, error, exhaustion, oversized doc): we
    leave ``safety_verdict`` as ``unknown`` (still excluded from search — fail
    closed) and only bump ``classification_attempts`` so the coordinator stops
    re-queuing it once it has retried enough times.

    Both writes are gated on ``content_hash`` (the version of the content that
    was actually classified) AND ``safety_verdict=unknown``. A crawl refresh
    keeps the same ``document_id`` while replacing the content and resetting the
    verdict to ``unknown`` with a new hash, so without this guard an attacker
    could have benign content classified, swap in a prompt-injection payload
    mid-flight, and have the stale ``safe`` verdict land on the new chunks. The
    guard makes the write a no-op whenever the content changed under us — the
    new content stays ``unknown`` (excluded) and is re-classified next pass.
    """
    base = KnowledgeDocument.objects.filter(
        team_id=team_id,
        id=document_id,
        content_hash=content_hash,
        safety_verdict=SafetyVerdict.UNKNOWN,
    )
    if verdict == SafetyVerdict.UNKNOWN:
        base.update(
            classification_attempts=F("classification_attempts") + 1,
            updated_at=timezone.now(),
        )
        return
    base.update(
        safety_verdict=verdict,
        safety_reason=reason[:1000],
        classification_attempts=0,
        updated_at=timezone.now(),
    )


def sweep_tombstoned_documents(*, older_than: datetime.timedelta = datetime.timedelta(days=7)) -> int:
    """
    Hard-delete documents tombstoned longer than ``older_than``.

    Chunks were already deleted when the doc was tombstoned; this reclaims the
    doc rows. Returns the number of documents deleted. Cross-team — coordinator
    only.
    """
    cutoff = timezone.now() - older_than
    deleted, _ = (
        KnowledgeDocument.objects.unscoped().filter(tombstoned_at__isnull=False, tombstoned_at__lt=cutoff).delete()
    )
    return deleted
