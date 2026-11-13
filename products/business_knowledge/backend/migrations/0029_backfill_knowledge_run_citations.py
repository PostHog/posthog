from uuid import UUID

from django.db import migrations

NOTE_BATCH_SIZE = 500


def _chunk_ids(citations: object) -> list[UUID]:
    """Keep the citations that are chunk ids. A note can also cite a docs URL."""
    if not isinstance(citations, list):
        return []
    chunk_ids: list[UUID] = []
    for citation in citations:
        try:
            chunk_id = UUID(str(citation).strip())
        except ValueError:
            continue
        if chunk_id not in chunk_ids:
            chunk_ids.append(chunk_id)
    return chunk_ids


def _ticket_id(item_id: object) -> UUID | None:
    try:
        return UUID(str(item_id))
    except ValueError:
        return None


def backfill_run_citations(apps, schema_editor):
    """Record the knowledge each existing AI note cited, one batch of notes at a time.

    A note written before run ids were stored stands for the one run that wrote it.
    The unique constraint makes a second pass add nothing.
    """
    Comment = apps.get_model("posthog", "Comment")
    Team = apps.get_model("posthog", "Team")
    KnowledgeChunk = apps.get_model("business_knowledge", "KnowledgeChunk")
    KnowledgeRunCitation = apps.get_model("business_knowledge", "KnowledgeRunCitation")
    db_alias = schema_editor.connection.alias

    notes = (
        Comment._base_manager.using(db_alias)
        .filter(scope="conversations_ticket", item_context__author_type="AI")
        .order_by("pk")
        .values("pk", "team_id", "item_id", "item_context", "created_at")
    )
    last_pk = None
    while True:
        page = notes if last_pk is None else notes.filter(pk__gt=last_pk)
        batch = list(page[:NOTE_BATCH_SIZE])
        if not batch:
            return
        last_pk = batch[-1]["pk"]

        cited = {note["pk"]: _chunk_ids((note["item_context"] or {}).get("citations")) for note in batch}
        # Knowledge rows live under the parent team, and a ticket can live in a child environment.
        parent_by_team = dict(
            Team._base_manager.using(db_alias)
            .filter(id__in={note["team_id"] for note in batch})
            .values_list("id", "parent_team_id")
        )
        chunks = {
            chunk["id"]: chunk
            for chunk in KnowledgeChunk._base_manager.using(db_alias)
            .filter(id__in={chunk_id for chunk_ids in cited.values() for chunk_id in chunk_ids})
            .values("id", "team_id", "document_id", "source_id")
        }

        rows = []
        for note in batch:
            ticket_id = _ticket_id(note["item_id"])
            if ticket_id is None:
                continue
            context = note["item_context"] or {}
            knowledge_team_id = parent_by_team.get(note["team_id"]) or note["team_id"]
            confidence = context.get("confidence")
            for chunk_id in cited[note["pk"]]:
                chunk = chunks.get(chunk_id)
                # A note must not record a chunk that belongs to another team.
                if chunk is None or chunk["team_id"] != knowledge_team_id:
                    continue
                rows.append(
                    KnowledgeRunCitation(
                        team_id=knowledge_team_id,
                        run_id=str(context.get("run_id") or f"note:{note['pk']}"),
                        ticket_id=ticket_id,
                        chunk_id=chunk_id,
                        document_id=chunk["document_id"],
                        source_id=chunk["source_id"],
                        persist_as=str(context.get("persist_as") or "")[:16],
                        confidence=float(confidence) if isinstance(confidence, int | float) else None,
                        created_at=note["created_at"],
                    )
                )
        if rows:
            KnowledgeRunCitation._base_manager.using(db_alias).bulk_create(rows, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("business_knowledge", "0028_knowledge_run_citation"),
    ]

    operations = [
        migrations.RunPython(backfill_run_citations, migrations.RunPython.noop, elidable=True),
    ]
