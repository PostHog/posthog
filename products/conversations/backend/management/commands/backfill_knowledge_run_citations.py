"""Record knowledge citations for AI notes written before run citations were stored."""

from __future__ import annotations

from uuid import UUID

from django.core.management.base import BaseCommand

from posthog.models.comment import Comment

from products.business_knowledge.backend.facade.api import record_run_citations

BATCH_SIZE = 500


def backfill_run_citations(*, team_id: int | None = None) -> int:
    """Record citations from every AI note. Returns how many notes cited knowledge.

    Recording is idempotent per run, so the command can run again after a failure.
    """
    notes = Comment.objects.filter(
        scope="conversations_ticket",
        item_context__author_type="AI",
        item_context__has_key="citations",
    )
    if team_id is not None:
        notes = notes.filter(team_id=team_id)
    recorded = 0
    for note in notes.order_by("id").iterator(chunk_size=BATCH_SIZE):
        context = note.item_context or {}
        citations = context.get("citations")
        if not isinstance(citations, list) or not citations or not note.item_id:
            continue
        try:
            ticket_id = UUID(str(note.item_id))
        except ValueError:
            continue
        confidence = context.get("confidence")
        cited = record_run_citations(
            team_id=note.team_id,
            # A note written before run ids were stored stands for the one run that wrote it.
            run_id=str(context.get("run_id") or f"note:{note.id}"),
            ticket_id=ticket_id,
            citations=[str(citation) for citation in citations],
            persist_as=str(context.get("persist_as") or ""),
            confidence=float(confidence) if isinstance(confidence, int | float) else None,
            cited_at=note.created_at,
        )
        if cited:
            recorded += 1
    return recorded


class Command(BaseCommand):
    help = "Record business knowledge citations for existing AI notes on support tickets."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--team-id", type=int, help="Limit the backfill to one team.")

    def handle(self, *args, **options) -> None:
        recorded = backfill_run_citations(team_id=options.get("team_id"))
        self.stdout.write(f"Recorded citations for {recorded} AI notes.")
