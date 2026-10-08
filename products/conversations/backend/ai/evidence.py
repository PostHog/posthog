"""Hydrate AI citation refs into titles and links for the ticket AI panel."""

from __future__ import annotations

from urllib.parse import urlparse
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.models.comment import Comment

from products.business_knowledge.backend.logic import GENERATED_KNOWLEDGE_ORIGIN
from products.business_knowledge.backend.models import KnowledgeChunk
from products.conversations.backend.models import Ticket

MAX_AI_SOURCES = 20


@frozen
class AiSource:
    ref: str
    title: str
    source_id: str | None = None
    url: str | None = None
    is_generated: bool = False
    learned_from_ticket_number: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ref": self.ref,
            "title": self.title,
            "source_id": self.source_id,
            "url": self.url,
            "is_generated": self.is_generated,
            "learned_from_ticket_number": self.learned_from_ticket_number,
        }


def outbound_doc_url(ref: str) -> str | None:
    parsed = urlparse(ref.strip())
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return ref.strip()
    return None


def parse_chunk_id(ref: str) -> UUID | None:
    try:
        return UUID(ref.strip())
    except ValueError:
        return None


def citations_for_ticket(ticket: Ticket, triage: dict[str, object]) -> list[str]:
    raw = triage.get("citations")
    if isinstance(raw, list):
        # An empty list is what the latest run stored, so the older comment below is stale.
        return [str(item) for item in raw if item][:MAX_AI_SOURCES]
    context = (
        Comment.objects.filter(
            team_id=ticket.team_id,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            item_context__author_type="AI",
            deleted=False,
        )
        .order_by("-created_at", "-id")
        .values_list("item_context", flat=True)
        .first()
    )
    if not isinstance(context, dict):
        return []
    stored = context.get("citations")
    if not isinstance(stored, list):
        return []
    return [str(item) for item in stored if item][:MAX_AI_SOURCES]


def hydrate_ai_sources(*, team_id: int, citations: list[str]) -> list[AiSource]:
    ordered = [item.strip() for item in citations if item and str(item).strip()][:MAX_AI_SOURCES]
    if not ordered:
        return []

    chunk_ids = [chunk_id for ref in ordered if (chunk_id := parse_chunk_id(ref)) is not None]
    chunks_by_id: dict[UUID, KnowledgeChunk] = {}
    if chunk_ids:
        # Search drops UNKNOWN learned chunks. Citation footnotes still have to
        # resolve those rows so the agent can see what the draft used.
        chunks_by_id = {
            chunk.id: chunk
            for chunk in KnowledgeChunk.objects.for_team(team_id)
            .filter(id__in=chunk_ids)
            .select_related("source", "document")
        }

    sources: list[AiSource] = []
    for ref in ordered:
        chunk_id = parse_chunk_id(ref)
        if chunk_id is not None:
            chunk = chunks_by_id.get(chunk_id)
            if chunk is None:
                sources.append(AiSource(ref=ref, title="Knowledge source"))
                continue
            sources.append(_source_from_chunk(ref, chunk))
            continue
        url = outbound_doc_url(ref)
        if url is not None:
            sources.append(AiSource(ref=ref, title=_url_title(url), url=url))
            continue
        sources.append(AiSource(ref=ref, title=ref[:80]))
    return sources


def _source_from_chunk(ref: str, chunk: KnowledgeChunk) -> AiSource:
    title = chunk.document.title or chunk.heading_path or chunk.source.name or "Knowledge source"
    metadata = chunk.document.metadata if isinstance(chunk.document.metadata, dict) else {}
    ticket_number = None
    if chunk.source.is_generated and metadata.get("origin") == GENERATED_KNOWLEDGE_ORIGIN:
        raw_number = metadata.get("ticket_number")
        if isinstance(raw_number, int) and raw_number > 0:
            ticket_number = raw_number
        elif isinstance(raw_number, str) and raw_number.isdigit() and int(raw_number) > 0:
            ticket_number = int(raw_number)
    return AiSource(
        ref=ref,
        title=title,
        source_id=str(chunk.source_id),
        is_generated=bool(chunk.source.is_generated),
        learned_from_ticket_number=ticket_number,
    )


def _url_title(url: str) -> str:
    parsed = urlparse(url)
    host_path = f"{parsed.netloc}{parsed.path}".rstrip("/")
    label = host_path or url
    return label[:80]
