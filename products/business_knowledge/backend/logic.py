"""
Business logic for business_knowledge.

All ORM access, chunking, quota enforcement, and search queries.
"""

import re
import uuid
import datetime
from collections import defaultdict
from dataclasses import dataclass
from functools import reduce
from operator import or_
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db import (
    connection as db_connection,
    transaction,
)
from django.db.models import Count, Exists, F, Max, OuterRef, Q, QuerySet
from django.db.models.functions import Substr
from django.utils import timezone

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from posthog.api.embedding_worker import generate_embedding
from posthog.helpers.full_text_search import process_query
from posthog.models.organization import OrganizationMembership
from posthog.models.scoping import with_team_scope
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false
from posthog.security.url_validation import is_url_allowed

from ee.hogai.llm import MaxChatAnthropic

from . import crawl, discover, file_parse, html_parse, url_fetch
from .constants import (
    BK_DRILLDOWN_DEFAULT_RADIUS,
    BK_DRILLDOWN_MAX_RADIUS,
    BK_EMBEDDING_DOCUMENT_TYPE,
    BK_EMBEDDING_MODEL,
    BK_EMBEDDING_PRODUCT,
    BK_RERANK_MODEL,
    BK_RERANK_SNIPPET_CHARS,
    BK_RRF_K,
    BK_RRF_SCORE_FLOOR,
    BK_SEMANTIC_DISTANCE_CUTOFF,
    BK_SEMANTIC_OVERFETCH,
    CHUNK_HARD_MAX_CHARS,
    CHUNK_TARGET_CHARS,
    CLASSIFY_MAX_ATTEMPTS,
    CLASSIFY_MAX_TOTAL_CHARS,
    CRAWL_HARD_MAX_DEPTH,
    DEFAULT_CRAWL_MAX_DEPTH,
    DEFAULT_MAX_PAGES,
    EMBEDDING_STABLE_TS_MAX_AGE,
    EMBEDDING_TTL_REFRESH_WINDOW,
    MAX_ALWAYS_ON_CONTEXT_CHARS,
    MAX_CHUNKS_PER_TEAM,
    MAX_SOURCES_PER_TEAM,
    MAX_TEXT_SIZE_BYTES,
    MAX_URLS_PER_SOURCE,
    PENDING_EMBEDDING_SCAN_CAP,
    RECONCILE_EMBEDDING_GRACE,
    RECONCILE_EMBEDDING_SCAN_CAP,
    REEMIT_EMBEDDING_SCAN_CAP,
)
from .models import (
    REFRESH_INTERVAL_TIMEDELTAS,
    CrawlMode,
    GapStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeGapSuggestion,
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
        KnowledgeChunk.objects.filter(team_id=team_id, id__in=[c.id for c in created]).update(
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


def _pending_embedding_documents_subquery() -> Exists:
    """
    Live docs that are still on their way into the semantic index: either
    awaiting safety classification (with retries left — docs past the attempt
    cap stay excluded forever, so they're not "pending"), or already SAFE with
    chunks but not yet produced to the embedding pipeline. Mirrors the
    eligibility rules of `_embeddable_documents_qs` so the API never reports
    "pending" for a doc the coordinator will never pick up.
    """
    has_chunks = Exists(KnowledgeChunk.objects.filter(document_id=OuterRef("pk")))
    return Exists(
        KnowledgeDocument.objects.filter(source_id=OuterRef("pk"), tombstoned_at__isnull=True).filter(
            Q(safety_verdict=SafetyVerdict.UNKNOWN, classification_attempts__lt=CLASSIFY_MAX_ATTEMPTS)
            | (Q(safety_verdict=SafetyVerdict.SAFE, embeddings_emitted_at__isnull=True) & Q(has_chunks))
        )
    )


def has_pending_embeddings(source_id: UUID) -> bool:
    """Standalone DB check — same logic as the annotation subquery."""
    return (
        KnowledgeDocument.objects.filter(
            source_id=source_id,
            tombstoned_at__isnull=True,
        )
        .filter(
            Q(safety_verdict=SafetyVerdict.UNKNOWN, classification_attempts__lt=CLASSIFY_MAX_ATTEMPTS)
            | Q(
                safety_verdict=SafetyVerdict.SAFE,
                embeddings_emitted_at__isnull=True,
                chunks__isnull=False,
            )
        )
        .exists()
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
            _has_pending_embeddings=_pending_embedding_documents_subquery(),
            _ai_processing_approved=F("team__organization__is_ai_data_processing_approved"),
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
            _has_pending_embeddings=_pending_embedding_documents_subquery(),
            _ai_processing_approved=F("team__organization__is_ai_data_processing_approved"),
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
    always_include: bool = False,
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
        always_include=always_include,
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
    always_include: bool | None = None,
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

    if always_include is not None:
        source.always_include = always_include

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
        if always_include is not None:
            update_fields.append("always_include")
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
    elif name is not None or always_include is not None:
        update_fields = ["updated_at"]
        if name is not None:
            source.name = name
            update_fields.append("name")
        if always_include is not None:
            update_fields.append("always_include")
        source.save(update_fields=update_fields)

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
    always_include: bool | None = None,
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

    if always_include is not None and always_include != source.always_include:
        source.always_include = always_include
        update_fields.append("always_include")

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
    always_include: bool = False,
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
            always_include=always_include,
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

    title, text = html_parse.parse_html(result.body, result.final_url, content_type=result.content_type)
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
    always_include: bool = False,
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
            always_include=always_include,
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
        # classification with a fresh attempt budget. The old chunk vectors are
        # stale too (and the chunk ids may shift), so clear the embedding stamp
        # to re-embed once the new content is re-classified SAFE.
        document.safety_verdict = SafetyVerdict.UNKNOWN
        document.safety_reason = ""
        document.classification_attempts = 0
        document.embeddings_emitted_at = None
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
                "embeddings_emitted_at",
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
        discovery = discover.discover(source.crawl_mode, normalized, config)
    except discover.DiscoverError as exc:
        return _mark_error(str(exc))

    candidate_urls = discovery.urls
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

    outcomes = crawl.fetch_many(safe_urls, prefetched=discovery.prefetched)
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
            discovery = discover.discover(source.crawl_mode, normalized, config)
            discovered = discovery.urls
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

    outcomes = crawl.fetch_many(safe_urls, etag_for=_etag_for, prefetched=discovery.prefetched)
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


@with_team_scope(canonical=True)
def get_always_on_context(team_id: int) -> "list[KnowledgeSearchResult]":
    """Return all SAFE/READY chunks from always_include sources, hard-capped by chars.

    Same safety gate as search — fails closed for UNKNOWN/unsafe/tombstoned/non-READY.
    Output is truncated to MAX_ALWAYS_ON_CONTEXT_CHARS worth of chunk content so
    always-on injection can't blow the prompt budget.
    """
    chunks = (
        _safe_chunks_qs(team_id)
        .filter(source__always_include=True)
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
        .order_by("source_id", "document_id", "ordinal")
    )

    results: list[KnowledgeSearchResult] = []
    total_chars = 0
    for c in chunks:
        # Account for the "\n\n" separator the caller joins chunks with, so the
        # assembled text honors the cap precisely (no mid-sentence slice downstream).
        separator = 2 if results else 0
        if total_chars + separator + len(c.content) > MAX_ALWAYS_ON_CONTEXT_CHARS:
            break
        total_chars += separator + len(c.content)
        results.append(
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
        )
    return results


def has_feature_flag(team: Team) -> bool:
    """The `product-business-knowledge` flag check, org-keyed. Canonical home for the
    check — `ee/hogai/utils/feature_flags.py` delegates here."""
    if settings.DEBUG:
        return True
    return feature_enabled_or_false(
        "product-business-knowledge",
        str(team.organization_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def is_available_for_team(team: Team) -> bool:
    """Feature flag + ready sources — the full "should agents use BK?" predicate."""
    return has_feature_flag(team) and has_ready_sources(team.id)


_SEARCH_LIMIT_CAP = 20


# ---------------------------------------------------------------------------
# Semantic search helpers (hybrid retrieval, gated on use_semantic)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SemanticCandidate:
    """A chunk_id + cosineDistance returned from ClickHouse vector search."""

    chunk_id: UUID
    distance: float


def _semantic_chunk_candidates(
    team_id: int,
    query_embedding: list[float],
    *,
    limit: int,
) -> list[_SemanticCandidate]:
    """
    Vector search over document_embeddings for BK chunks.

    Returns up to ``limit * BK_SEMANTIC_OVERFETCH`` candidates under the
    distance cutoff, ordered by cosineDistance ASC. The caller re-joins to
    Postgres for safety filters and trims to ``limit``.
    """
    from posthog.hogql import ast  # noqa: PLC0415 — keeps HogQL compiler off the import path
    from posthog.hogql.query import execute_hogql_query  # noqa: PLC0415

    from posthog.clickhouse.query_tagging import Feature, Product, tag_queries  # noqa: PLC0415
    from posthog.models.team.team import Team  # noqa: PLC0415

    ch_limit = limit * BK_SEMANTIC_OVERFETCH

    # Distance is computed in the inner SELECT and filtered in the outer WHERE
    # so cosineDistance runs once per row (ClickHouse can't reuse a SELECT alias
    # in the same level's WHERE — WHERE is evaluated first). Matters at 1536 dims.
    hogql_query = """
        SELECT document_id, distance
        FROM (
            SELECT
                document_id,
                cosineDistance(embedding, {embedding}) AS distance
            FROM document_embeddings
            WHERE model_name = {model_name}
              AND product = {product}
              AND document_type = {document_type}
              AND team_id = {team_id}
        )
        WHERE distance < {cutoff}
        ORDER BY distance ASC
        LIMIT {limit}
    """

    placeholders: dict[str, ast.Expr] = {
        "embedding": ast.Constant(value=query_embedding),
        "model_name": ast.Constant(value=BK_EMBEDDING_MODEL),
        "product": ast.Constant(value=BK_EMBEDDING_PRODUCT),
        "document_type": ast.Constant(value=BK_EMBEDDING_DOCUMENT_TYPE),
        "team_id": ast.Constant(value=team_id),
        "cutoff": ast.Constant(value=BK_SEMANTIC_DISTANCE_CUTOFF),
        "limit": ast.Constant(value=ch_limit),
    }

    team = Team.objects.get(pk=team_id)
    tag_queries(product=Product.CONVERSATIONS, feature=Feature.SEMANTIC_SEARCH)
    result = execute_hogql_query(
        query=hogql_query,
        team=team,
        placeholders=placeholders,
    )

    candidates: list[_SemanticCandidate] = []
    for row in result.results or []:
        doc_id_str, distance = row
        try:
            candidates.append(_SemanticCandidate(chunk_id=UUID(doc_id_str), distance=float(distance)))
        except (ValueError, TypeError):
            continue
    return candidates


def _rrf_fuse(
    fts_chunk_ids: list[UUID],
    semantic_candidates: list[_SemanticCandidate],
    *,
    k: int = BK_RRF_K,
    score_floor: float = BK_RRF_SCORE_FLOOR,
) -> list[UUID]:
    """
    Reciprocal Rank Fusion of FTS anchors and semantic candidates.

    Each list contributes 1/(k + rank) per candidate. FTS anchors are always
    kept (they're real lexical matches against SAFE/READY content); only
    semantic-ONLY candidates are subject to ``score_floor``, so a borderline
    semantic hit on an off-topic query is dropped without trimming the
    legitimate FTS tail.

    Semantic candidates are deduped by chunk_id first: the shared
    ``document_embeddings`` table is a ReplacingMergeTree that we do NOT read
    with FINAL, so a re-emitted chunk can appear as several rows. Keeping the
    first occurrence (the CH query is ordered by distance ASC, so that's the
    closest) prevents a duplicated vector from double-counting its RRF score.
    """
    scores: dict[UUID, float] = defaultdict(float)
    fts_ids = set(fts_chunk_ids)

    for rank, chunk_id in enumerate(fts_chunk_ids, start=1):
        scores[chunk_id] += 1.0 / (k + rank)

    seen_semantic: set[UUID] = set()
    semantic_rank = 0
    for candidate in semantic_candidates:
        if candidate.chunk_id in seen_semantic:
            continue
        seen_semantic.add(candidate.chunk_id)
        semantic_rank += 1
        scores[candidate.chunk_id] += 1.0 / (k + semantic_rank)

    # FTS anchors bypass the floor; semantic-only candidates must clear it.
    fused = [(cid, score) for cid, score in scores.items() if cid in fts_ids or score >= score_floor]
    fused.sort(key=lambda x: x[1], reverse=True)
    return [cid for cid, _score in fused]


def _safe_chunks_qs(team_id: int) -> QuerySet[KnowledgeChunk]:
    """Base queryset for searchable/readable chunks: team-scoped + all safety gates."""
    return KnowledgeChunk.objects.filter(
        team_id=team_id,
        source__status=SourceStatus.READY,
        document__tombstoned_at__isnull=True,
        document__safety_verdict=SafetyVerdict.SAFE,
    )


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
    use_semantic: bool = False,
    query_embedding: list[float] | None = None,
) -> list[KnowledgeSearchResult]:
    """
    Hybrid (lexical + semantic) relevance search over BK chunks.

    When ``use_semantic=False`` (default / flag off), this is pure FTS — the
    existing keyword path byte-for-byte.

    When ``use_semantic=True``, the caller must also pass ``query_embedding``
    (the pre-computed query vector). Both FTS and vector results are fused via
    Reciprocal Rank Fusion (RRF), safety-re-joined against Postgres, trimmed
    to ``limit``, and ordinal-neighbour-expanded.
    """
    limit = max(1, min(limit, _SEARCH_LIMIT_CAP))

    # --- FTS anchors (always computed) ---
    processed = process_query(query)
    fts_anchors: list[KnowledgeChunk] = []
    if processed is not None:
        processed = processed.replace(" & ", " | ")
        search_query = SearchQuery(processed, config="english", search_type="raw")
        fts_anchors = list(
            _safe_chunks_qs(team_id)
            .filter(content_search_vector=search_query)
            .annotate(rank=SearchRank(F("content_search_vector"), search_query))
            .only("id", "document_id", "ordinal", "char_count")
            .order_by("-rank", "char_count", "id")[:limit]
        )
    fts_anchor_ids = [a.id for a in fts_anchors]

    # --- Semantic candidates (hybrid path only) ---
    semantic_candidates: list[_SemanticCandidate] = []
    if use_semantic and query_embedding:
        semantic_candidates = _semantic_chunk_candidates(team_id, query_embedding, limit=limit)

    # --- Fusion or FTS-only ---
    # Fusion requires an actual embedding; when it's None (e.g. embedding-service
    # timeout) semantic_candidates is empty, so fall through to the FTS-only
    # branch which reuses the already-filtered, rank-ordered anchors.
    if use_semantic and query_embedding and (fts_anchor_ids or semantic_candidates):
        fused_ids = _rrf_fuse(fts_anchor_ids, semantic_candidates)
        if not fused_ids:
            return []
        # Semantic candidates may reference now-unsafe/tombstoned chunks, so we
        # re-join against Postgres with all safety filters and trim after.
        fetch_limit = limit * BK_SEMANTIC_OVERFETCH
        anchor_chunks = list(
            _safe_chunks_qs(team_id).filter(id__in=fused_ids[:fetch_limit]).only("id", "document_id", "ordinal")
        )
        if not anchor_chunks:
            return []
        id_to_rank = {cid: rank for rank, cid in enumerate(fused_ids)}
        anchor_chunks.sort(key=lambda c: id_to_rank.get(c.id, len(fused_ids)))
        anchor_chunks = anchor_chunks[:limit]
    elif fts_anchors:
        # FTS anchors are already safety-filtered — use them directly (no
        # extra query). Already ordered by rank from the FTS query.
        anchor_chunks = fts_anchors
    else:
        return []

    # --- Ordinal neighbour expansion ---
    doc_rank: dict[UUID, int] = {}
    wanted_ordinals: dict[UUID, set[int]] = {}
    for rank, anchor in enumerate(anchor_chunks):
        doc_rank.setdefault(anchor.document_id, rank)
        wanted_ordinals.setdefault(anchor.document_id, set()).update(
            (anchor.ordinal - 1, anchor.ordinal, anchor.ordinal + 1)
        )

    window_filter = reduce(
        or_,
        (Q(document_id=doc_id, ordinal__in=sorted(ords)) for doc_id, ords in wanted_ordinals.items()),
    )

    chunks = (
        _safe_chunks_qs(team_id)
        .filter(window_filter)
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

    ordered = sorted(chunks, key=lambda c: (doc_rank.get(c.document_id, len(anchor_chunks)), c.ordinal))

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


def search_knowledge_for_team(
    team: Team,
    query: str,
    *,
    limit: int = 10,
) -> list[KnowledgeSearchResult]:
    """
    Sync orchestration of hybrid BK search: embed the query, then call
    ``search_knowledge``. Falls back to FTS-only on any embedding failure.

    Used by the DRF search endpoint (sync view). The async PHAI tool path
    uses ``async_generate_embedding`` directly — they share ``search_knowledge``
    as the common layer, not this wrapper.
    """
    embedding: list[float] | None = None
    try:
        embedding = generate_embedding(team, query, model=BK_EMBEDDING_MODEL).embedding
    except Exception:
        logger.warning("bk_query_embedding_failed", team_id=team.id, exc_info=True)
    return search_knowledge(team.id, query, limit=limit, use_semantic=embedding is not None, query_embedding=embedding)


_RERANK_CHUNK_ID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_RERANK_SYSTEM_PROMPT = """You rerank knowledge-base search results for relevance to a user query.
Return ONLY chunk_id UUIDs in order from most to least relevant, one UUID per line.
Do not include any other text."""


def _resolve_active_org_user(team: Team) -> User:
    membership = (
        OrganizationMembership.objects.select_related("user")
        .filter(organization=team.organization, user__is_active=True)
        .order_by("id")
        .first()
    )
    if not membership:
        raise RuntimeError(f"No active users in organization '{team.organization.name}' (team {team.id})")
    return membership.user


def _build_rerank_user_prompt(query: str, results: list[KnowledgeSearchResult]) -> str:
    lines = [f"Query: {query}", "", "Candidates:"]
    for index, result in enumerate(results, start=1):
        snippet = result.content[:BK_RERANK_SNIPPET_CHARS]
        lines.append(
            f"{index}. chunk_id={result.chunk_id} document={result.document_title!r} heading={result.heading_path!r}"
        )
        lines.append(f"   {snippet}")
    lines.extend(["", "Most relevant chunk_ids first, one per line:"])
    return "\n".join(lines)


def _parse_reranked_chunk_ids(response_text: str, valid_ids: set[UUID]) -> list[UUID] | None:
    parsed: list[UUID] = []
    seen: set[UUID] = set()
    for match in _RERANK_CHUNK_ID_PATTERN.finditer(response_text):
        chunk_id = UUID(match.group())
        if chunk_id not in valid_ids or chunk_id in seen:
            continue
        parsed.append(chunk_id)
        seen.add(chunk_id)
    if not parsed:
        return None
    return parsed


def rerank_chunks(
    team: Team,
    query: str,
    results: list[KnowledgeSearchResult],
    *,
    top_k: int,
) -> list[KnowledgeSearchResult]:
    """
    Listwise LLM rerank over BK search candidates. On any model/parse failure,
    returns the input order (RRF order from ``search_knowledge``) trimmed to
    ``top_k``.
    """
    if not results:
        return []

    top_k = max(1, top_k)
    original_order = results
    if len(results) == 1:
        return original_order[:top_k]

    if not team.organization.is_ai_data_processing_approved:
        return original_order[:top_k]

    valid_ids = {result.chunk_id for result in results}
    id_to_result = {result.chunk_id: result for result in results}

    try:
        user = _resolve_active_org_user(team)
        llm = MaxChatAnthropic(
            model=BK_RERANK_MODEL,
            streaming=False,
            user=user,
            team=team,
            max_tokens=1024,
            billable=False,
            inject_context=False,
        )
        response = llm.invoke(
            [
                SystemMessage(content=_RERANK_SYSTEM_PROMPT),
                HumanMessage(content=_build_rerank_user_prompt(query, results)),
            ]
        )
        content = response.content
        if isinstance(content, list):
            content = "".join(str(item) for item in content)
        ranked_ids = _parse_reranked_chunk_ids(str(content), valid_ids)
        if ranked_ids is None:
            return original_order[:top_k]

        ranked_set = set(ranked_ids)
        for result in original_order:
            if result.chunk_id not in ranked_set:
                ranked_ids.append(result.chunk_id)

        reranked = [id_to_result[chunk_id] for chunk_id in ranked_ids]
        return reranked[:top_k]
    except Exception:
        logger.warning("bk_rerank_failed", team_id=team.id, exc_info=True)
        return original_order[:top_k]


# ---------------------------------------------------------------------------
# Drill-down: wider context window for a single document
# ---------------------------------------------------------------------------


@with_team_scope(canonical=True)
def get_document_window(
    team_id: int,
    document_id: UUID,
    center_ordinal: int,
    *,
    radius: int = BK_DRILLDOWN_DEFAULT_RADIUS,
) -> list[KnowledgeSearchResult]:
    """
    Return a contiguous span of chunks from one document, centered on
    ``center_ordinal``. Reuses the exact same safety filters as
    ``search_knowledge`` so drill-down can never surface content that search
    wouldn't return.
    """
    radius = max(0, min(radius, BK_DRILLDOWN_MAX_RADIUS))
    center_ordinal = max(0, center_ordinal)
    low = max(0, center_ordinal - radius)
    high = center_ordinal + radius

    chunks = (
        _safe_chunks_qs(team_id)
        .filter(document_id=document_id, ordinal__gte=low, ordinal__lte=high)
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
        .order_by("ordinal")
    )

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
        for c in chunks
    ]


@with_team_scope(canonical=True)
def get_chunks_by_ids(team_id: int, chunk_ids: list[UUID]) -> list[KnowledgeSearchResult]:
    """
    Rehydrate full chunk content + source context for a set of chunk ids,
    preserving the order of ``chunk_ids`` and dropping any id that no longer
    resolves (unsafe/tombstoned/deleted). Applies the same safety filters as
    ``search_knowledge``.

    Lets callers pass chunk ids across a process/serialization boundary (e.g.
    between Temporal activities) and re-fetch content on demand — deterministic
    retrieval — instead of shipping the content itself through workflow history.
    """
    if not chunk_ids:
        return []

    chunks = (
        _safe_chunks_qs(team_id)
        .filter(id__in=chunk_ids)
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
    by_id = {c.id: c for c in chunks}
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
        for chunk_id in chunk_ids
        if (c := by_id.get(chunk_id)) is not None
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


# ---------------------------------------------------------------------------
# Embedding-pipeline coordinator helpers (cross-team)
#
# Like the classification helpers above, these run inside Temporal activities
# and scan across teams via `.unscoped()`. They only read/write Postgres; the
# actual produce-to-Kafka and ClickHouse presence check live in the coordinator
# activity so this module stays free of Kafka / ClickHouse dependencies.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChunkToEmbed:
    chunk_id: UUID
    content: str


@dataclass(frozen=True)
class DocumentToEmbed:
    """A SAFE document whose chunks need producing to the embedding pipeline."""

    team_id: int
    document_id: UUID
    # The embedding row `timestamp`. Young docs use the stable `created_at` so
    # a re-emit of the same chunk_id collapses onto one ClickHouse sort key /
    # partition instead of duplicating under a later `toDate(timestamp)`.
    # Old docs (created_at older than EMBEDDING_STABLE_TS_MAX_AGE) and the
    # TTL-refresh path use `now()` so the row survives until the refresh cron
    # fires, instead of expiring under `TTL timestamp + 3 MONTH` first. The
    # extra row is correctness-safe via the read-path re-join.
    timestamp: datetime.datetime
    chunks: list[ChunkToEmbed]


@dataclass(frozen=True)
class EmittedDocument:
    """An already-emitted SAFE document, for ClickHouse-presence reconciliation."""

    team_id: int
    document_id: UUID
    chunk_ids: list[UUID]


def _embeddable_documents_qs() -> QuerySet[KnowledgeDocument]:
    """Base queryset of docs eligible to be embedded: SAFE, live, READY source,
    and an org that approved AI data processing (we must not send content to the
    embedding service otherwise — same gate as classification). Cross-team.

    Zero-chunk docs are excluded: there's nothing to embed, and letting one
    through would loop forever — emit stamps it with no produce, then
    reconciliation finds no vectors in ClickHouse and clears the stamp, putting
    it right back in the pending queue. A SAFE doc with no chunks is unlikely but
    reachable (e.g. whitespace-only content), so we filter it out at the source.
    """
    return (
        KnowledgeDocument.objects.unscoped()
        .filter(
            safety_verdict=SafetyVerdict.SAFE,
            tombstoned_at__isnull=True,
            source__status=SourceStatus.READY,
            team__organization__is_ai_data_processing_approved=True,
        )
        .filter(Exists(KnowledgeChunk.objects.unscoped().filter(document_id=OuterRef("pk"))))
    )


def _chunks_to_embed_by_document(document_ids: list[UUID]) -> dict[UUID, list[ChunkToEmbed]]:
    """Load chunk content for many docs in ONE query, grouped by document_id and
    ordered by ordinal within each doc. Avoids an N+1 (one query per pending
    doc). Cross-team."""
    by_doc: dict[UUID, list[ChunkToEmbed]] = defaultdict(list)
    for document_id, chunk_id, content in (
        KnowledgeChunk.objects.unscoped()
        .filter(document_id__in=document_ids)
        .order_by("document_id", "ordinal")
        .values_list("document_id", "id", "content")
    ):
        by_doc[document_id].append(ChunkToEmbed(chunk_id=chunk_id, content=content))
    return by_doc


def _chunk_ids_by_document(document_ids: list[UUID]) -> dict[UUID, list[UUID]]:
    """Load chunk ids for many docs in ONE query, grouped by document_id. Avoids
    an N+1 in reconciliation. Cross-team."""
    by_doc: dict[UUID, list[UUID]] = defaultdict(list)
    for document_id, chunk_id in (
        KnowledgeChunk.objects.unscoped().filter(document_id__in=document_ids).values_list("document_id", "id")
    ):
        by_doc[document_id].append(chunk_id)
    return by_doc


def list_documents_pending_embedding(*, limit: int = PENDING_EMBEDDING_SCAN_CAP) -> list[DocumentToEmbed]:
    """
    Return SAFE documents that have not yet had their chunks produced to the
    embedding pipeline (``embeddings_emitted_at IS NULL``).

    Bounded by ``limit`` (loads chunk content per doc into memory, same rationale
    as ``list_documents_pending_classification``). The first post-deploy pass
    backfills every existing SAFE doc across all teams, so the cap is what lets
    the hourly coordinator drain that over many passes. Cross-team — coordinator
    only.

    Timestamp strategy: young docs use the stable ``created_at`` so a re-emit
    collapses onto one ClickHouse sort key. Old docs (``created_at`` older than
    ``EMBEDDING_STABLE_TS_MAX_AGE``) use ``now()``: a stable timestamp is only
    safe if the row survives until the TTL-refresh cron re-emits the doc at
    ``emitted_at + EMBEDDING_TTL_REFRESH_WINDOW`` — beyond the max age the row
    would expire first (in the worst case it lands already expired,
    reconciliation re-nulls it, and the next pass re-emits with ``created_at``
    again: a token-burning loop while the doc silently serves FTS-only forever).
    """
    now = timezone.now()
    ttl_cutoff = now - EMBEDDING_STABLE_TS_MAX_AGE
    rows = list(
        _embeddable_documents_qs()
        .filter(embeddings_emitted_at__isnull=True)
        .values_list("team_id", "id", "created_at")[:limit]
    )
    chunks_by_doc = _chunks_to_embed_by_document([document_id for _team_id, document_id, _created_at in rows])
    return [
        DocumentToEmbed(
            team_id=team_id,
            document_id=document_id,
            timestamp=now if created_at < ttl_cutoff else created_at,
            chunks=chunks_by_doc.get(document_id, []),
        )
        for team_id, document_id, created_at in rows
    ]


def list_documents_for_embedding_reconciliation(
    *,
    now: datetime.datetime | None = None,
    grace: datetime.timedelta = RECONCILE_EMBEDDING_GRACE,
    limit: int = RECONCILE_EMBEDDING_SCAN_CAP,
) -> list[EmittedDocument]:
    """
    Return already-emitted SAFE docs (oldest first) whose vectors should by now
    be in ClickHouse, so the coordinator can re-verify they actually landed.

    ``embeddings_emitted_at`` only means "produced to Kafka", not "present in
    ClickHouse": a transient produce failure that did NOT raise, or a worker
    that dropped the message, leaves a SAFE doc permanently serving FTS-only.
    The grace window skips docs whose vectors are merely still in flight.
    Cross-team — coordinator only.
    """
    now = now or timezone.now()
    cutoff = now - grace
    rows = list(
        _embeddable_documents_qs()
        .filter(embeddings_emitted_at__isnull=False, embeddings_emitted_at__lt=cutoff)
        .order_by("embeddings_emitted_at")
        .values_list("team_id", "id")[:limit]
    )
    chunk_ids_by_doc = _chunk_ids_by_document([document_id for _team_id, document_id in rows])
    return [
        EmittedDocument(
            team_id=team_id,
            document_id=document_id,
            chunk_ids=chunk_ids_by_doc.get(document_id, []),
        )
        for team_id, document_id in rows
    ]


def list_documents_for_embedding_refresh(
    *,
    now: datetime.datetime | None = None,
    window: datetime.timedelta = EMBEDDING_TTL_REFRESH_WINDOW,
    limit: int = REEMIT_EMBEDDING_SCAN_CAP,
) -> list[DocumentToEmbed]:
    """
    Return already-emitted SAFE docs (oldest-emitted first) whose vectors are
    aging toward the 3-month ClickHouse TTL, so their chunks can be re-emitted
    before the rows expire and the doc silently drops to FTS-only.

    The returned ``DocumentToEmbed.timestamp`` is ``now`` (NOT the doc's
    ``created_at``): the shared table TTLs on the embedding row ``timestamp``,
    so the re-emit must carry a fresh timestamp to actually reset the clock —
    re-emitting under the old ``created_at`` would land an already-/soon-expired
    row and keep losing vectors. The extra row this creates is correctness-safe:
    the read path always re-joins to Postgres and dedups candidates by chunk_id.
    Cross-team — coordinator only.
    """
    now = now or timezone.now()
    cutoff = now - window
    rows = list(
        _embeddable_documents_qs()
        .filter(embeddings_emitted_at__isnull=False, embeddings_emitted_at__lt=cutoff)
        .order_by("embeddings_emitted_at")
        .values_list("team_id", "id")[:limit]
    )
    chunks_by_doc = _chunks_to_embed_by_document([document_id for _team_id, document_id in rows])
    return [
        DocumentToEmbed(
            team_id=team_id,
            document_id=document_id,
            timestamp=now,
            chunks=chunks_by_doc.get(document_id, []),
        )
        for team_id, document_id in rows
    ]


@with_team_scope(canonical=True)
def mark_document_embeddings_emitted(*, team_id: int, document_id: UUID) -> None:
    """
    Stamp ``embeddings_emitted_at`` after a successful produce.

    Gated on the doc still being SAFE and unstamped: a concurrent content change
    resets the verdict to ``unknown`` and the stamp to NULL, and we must never
    mark that new (unembedded) content as emitted. The guard makes this a no-op
    in that race, so the new content is re-embedded on a later pass.
    """
    KnowledgeDocument.objects.filter(
        team_id=team_id,
        id=document_id,
        safety_verdict=SafetyVerdict.SAFE,
        embeddings_emitted_at__isnull=True,
    ).update(embeddings_emitted_at=timezone.now(), updated_at=timezone.now())


@with_team_scope(canonical=True)
def restamp_document_embeddings_emitted(*, team_id: int, document_id: UUID) -> None:
    """
    Bump ``embeddings_emitted_at`` to now after a TTL-refresh re-emit.

    Unlike ``mark_document_embeddings_emitted`` (gated on NULL, for first
    emission), this re-stamps an ALREADY-stamped doc so it drops out of the
    refresh window for another full cycle. Still gated on the doc being SAFE
    AND already stamped: a content change that flipped it to ``unknown``
    mid-pass NULLs the stamp, and that new (unembedded) content must go through
    the normal pending-emit path rather than being re-stamped here.
    """
    KnowledgeDocument.objects.filter(
        team_id=team_id,
        id=document_id,
        safety_verdict=SafetyVerdict.SAFE,
        embeddings_emitted_at__isnull=False,
    ).update(embeddings_emitted_at=timezone.now(), updated_at=timezone.now())


@with_team_scope(canonical=True)
def clear_document_embeddings_emitted(*, team_id: int, document_id: UUID) -> None:
    """
    Reset the emission stamp to NULL so the next pending pass re-emits.

    Used by reconciliation when a doc's vectors never landed in ClickHouse.
    """
    KnowledgeDocument.objects.filter(team_id=team_id, id=document_id).update(
        embeddings_emitted_at=None, updated_at=timezone.now()
    )


# ---------------------------------------------------------------------------
# Knowledge gap suggestions
# ---------------------------------------------------------------------------

_GAP_NOISE_TOPICS = frozenset({"parse_failure"})


def _normalize_topic(topic: str) -> str:
    return topic.strip().lower()[:255]


def upsert_knowledge_gaps(
    team_id: int,
    ticket_id: str,
    topics: list[str],
    ticket_type: str = "",
    outcome: str = "",
) -> int:
    """Create one KnowledgeGapSuggestion per (ticket, normalized topic).

    Idempotent via the unique constraint — safe under Temporal activity retries.
    Returns the number of rows created (not the total including existing ones).
    """
    created_count = 0
    for raw_topic in topics:
        normalized = _normalize_topic(raw_topic)
        if not normalized or normalized in _GAP_NOISE_TOPICS:
            continue
        _, created = KnowledgeGapSuggestion.objects.for_team(team_id).get_or_create(
            team_id=team_id,
            ticket_id=ticket_id,
            normalized_topic=normalized,
            defaults={
                "topic": raw_topic.strip(),
                "ticket_type": ticket_type,
                "outcome": outcome,
            },
        )
        if created:
            created_count += 1
    return created_count


def list_gap_suggestions_for_ticket(
    team_id: int,
    ticket_id: str,
) -> QuerySet[KnowledgeGapSuggestion]:
    return KnowledgeGapSuggestion.objects.for_team(team_id).filter(ticket_id=ticket_id).order_by("-created_at")


@dataclass
class AggregatedGap:
    normalized_topic: str
    topic: str
    ticket_count: int


def aggregate_gap_suggestions(
    team_id: int,
    status: str = GapStatus.PENDING,
    limit: int = 50,
) -> list[AggregatedGap]:
    """Group pending gaps by normalized_topic, ranked by ticket count."""
    rows = (
        KnowledgeGapSuggestion.objects.for_team(team_id)
        .filter(status=status)
        .values("normalized_topic")
        .annotate(
            ticket_count=Count("ticket_id", distinct=True),
            representative_topic=Substr(Max("topic"), 1, 500),
        )
        .order_by("-ticket_count")[:limit]
    )
    return [
        AggregatedGap(
            normalized_topic=r["normalized_topic"],
            topic=r["representative_topic"],
            ticket_count=r["ticket_count"],
        )
        for r in rows
    ]


def set_gap_status(
    team_id: int,
    *,
    suggestion_id: UUID | None = None,
    normalized_topic: str | None = None,
    status: str,
    resolved_source_id: UUID | None = None,
    only_pending: bool = False,
) -> int:
    """Accept or dismiss gap suggestions. Returns updated row count.

    Pass suggestion_id for a single row, or normalized_topic to flip the whole
    cluster (all tickets with that topic). Set only_pending=True to restrict
    the update to rows still in PENDING status.
    """
    qs = KnowledgeGapSuggestion.objects.for_team(team_id)
    if suggestion_id is not None:
        qs = qs.filter(id=suggestion_id)
    elif normalized_topic is not None:
        qs = qs.filter(normalized_topic=normalized_topic)
    else:
        raise ValueError("One of suggestion_id or normalized_topic is required")

    if only_pending:
        qs = qs.filter(status=GapStatus.PENDING)

    update_kwargs: dict[str, object] = {"status": status}
    if resolved_source_id is not None:
        update_kwargs["resolved_source_id"] = resolved_source_id
    return qs.update(**update_kwargs)
