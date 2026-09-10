import re
import uuid
from uuid import UUID

from django.db import transaction

from posthog.models.scoping import team_scope
from posthog.models.scoping.manager import resolve_effective_team_id

from . import logic
from .constants import MAX_CHUNKS_PER_TEAM, MAX_TEXT_SIZE_BYTES
from .facade.contracts import CreateGeneratedKnowledgeDocument
from .models import KnowledgeDocument, KnowledgeSource, SafetyVerdict, SourceStatus, SourceType
from .url_fetch import sha256_of

GENERATED_SOURCE_NAME = "Generated from resolved tickets"
GENERATED_KNOWLEDGE_ORIGIN = "resolved_ticket_gap"
MAX_ANALYSIS_VERSION_LENGTH = 128
MAX_DOCUMENT_TITLE_LENGTH = 512


class InvalidGeneratedKnowledgeDocument(ValueError):
    """The generated document violates the internal write contract."""


def _validate_input(document_input: CreateGeneratedKnowledgeDocument) -> tuple[str, str, str]:
    analysis_version = document_input.analysis_version.strip()
    title = document_input.title.strip()
    content = document_input.content

    if not analysis_version or len(analysis_version) > MAX_ANALYSIS_VERSION_LENGTH:
        raise InvalidGeneratedKnowledgeDocument("analysis_version is invalid")
    if re.fullmatch(r"[A-Za-z0-9._-]+", analysis_version) is None:
        raise InvalidGeneratedKnowledgeDocument("analysis_version is invalid")
    if not title or len(title) > MAX_DOCUMENT_TITLE_LENGTH:
        raise InvalidGeneratedKnowledgeDocument("title is invalid")
    if not content.strip():
        raise InvalidGeneratedKnowledgeDocument("content is empty")
    if len(content.encode("utf-8")) > MAX_TEXT_SIZE_BYTES:
        raise InvalidGeneratedKnowledgeDocument("content is too large")
    combined_content = f"{title}\n{content}".lower()
    if any(
        str(provenance_id).lower() in combined_content
        for provenance_id in (document_input.ticket_id, document_input.resolution_comment_id)
    ):
        raise InvalidGeneratedKnowledgeDocument("provenance identifiers cannot appear in generated content")

    return analysis_version, title, content


def _source_id(team_id: int) -> UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"team-{team_id}.generated.business-knowledge.posthog")


def _document_stable_id(document_input: CreateGeneratedKnowledgeDocument, analysis_version: str) -> str:
    return (
        f"{GENERATED_KNOWLEDGE_ORIGIN}:"
        f"{document_input.ticket_id}:{document_input.resolution_comment_id}:{analysis_version}"
    )


def _validate_existing_document(
    document: KnowledgeDocument,
    *,
    expected_id: UUID,
    source: KnowledgeSource,
    stable_id: str,
    team_id: int,
) -> None:
    if (
        document.id != expected_id
        or document.team_id != team_id
        or document.source_id != source.id
        or document.stable_id != stable_id
    ):
        raise InvalidGeneratedKnowledgeDocument("generated document identity is already in use")


def set_generated_source_ready(team_id: int, *, ready: bool) -> bool:
    canonical_team_id = resolve_effective_team_id(team_id)
    with team_scope(canonical_team_id, canonical=True):
        try:
            source = KnowledgeSource.objects.get(
                id=_source_id(canonical_team_id),
                team_id=canonical_team_id,
                is_generated=True,
            )
        except KnowledgeSource.DoesNotExist:
            return False
        source.status = SourceStatus.READY if ready else SourceStatus.ERROR
        source.error_message = "" if ready else "Generated source is disabled."
        source.save(update_fields=["status", "error_message", "updated_at"])
        return True


@transaction.atomic
def create_generated_document(
    document_input: CreateGeneratedKnowledgeDocument,
) -> tuple[KnowledgeDocument, bool]:
    canonical_team_id = resolve_effective_team_id(document_input.team_id)
    with team_scope(canonical_team_id, canonical=True):
        return _create_generated_document(document_input, team_id=canonical_team_id)


def _create_generated_document(
    document_input: CreateGeneratedKnowledgeDocument,
    *,
    team_id: int,
) -> tuple[KnowledgeDocument, bool]:
    analysis_version, title, content = _validate_input(document_input)
    logic._acquire_source_quota_lock(team_id)

    source, _ = KnowledgeSource.objects.get_or_create(
        id=_source_id(team_id),
        team_id=team_id,
        defaults={
            "created_by_id": None,
            "name": GENERATED_SOURCE_NAME,
            "source_type": SourceType.TEXT,
            "is_generated": True,
            "status": SourceStatus.READY,
        },
    )
    if not source.is_generated or source.source_type != SourceType.TEXT:
        raise InvalidGeneratedKnowledgeDocument("generated source identity is already in use")

    stable_id = _document_stable_id(document_input, analysis_version)
    document_id = uuid.uuid5(source.id, stable_id)
    existing = KnowledgeDocument.objects.filter(
        team_id=team_id,
        source=source,
        stable_id=stable_id,
    ).first()
    if existing is not None:
        _validate_existing_document(
            existing,
            expected_id=document_id,
            source=source,
            stable_id=stable_id,
            team_id=team_id,
        )
        return existing, False

    existing = KnowledgeDocument.objects.filter(id=document_id, team_id=team_id).first()
    if existing is not None:
        _validate_existing_document(
            existing,
            expected_id=document_id,
            source=source,
            stable_id=stable_id,
            team_id=team_id,
        )
        return existing, False

    document, created = KnowledgeDocument.objects.get_or_create(
        id=document_id,
        team_id=team_id,
        source=source,
        stable_id=stable_id,
        defaults={
            "title": title,
            "content": content,
            "metadata": {
                "source_type": SourceType.TEXT,
                "origin": GENERATED_KNOWLEDGE_ORIGIN,
                "ticket_id": str(document_input.ticket_id),
                "resolution_comment_id": str(document_input.resolution_comment_id),
                "analysis_version": analysis_version,
            },
            "content_hash": sha256_of(content),
            "safety_verdict": SafetyVerdict.UNKNOWN,
        },
    )
    _validate_existing_document(
        document,
        expected_id=document_id,
        source=source,
        stable_id=stable_id,
        team_id=team_id,
    )
    if not created:
        return document, False

    chunks = logic.chunk_text(content)
    if logic._count_chunks(team_id) + len(chunks) > MAX_CHUNKS_PER_TEAM:
        raise logic.QuotaExceededError("Generated content exceeds the remaining team chunk budget.")

    logic._bulk_create_chunks(source=source, document=document, team_id=team_id, chunks=chunks)
    return document, True
