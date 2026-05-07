from django.contrib.postgres.indexes import GinIndex
from django.db import models

from posthog.models.scoping.manager import TeamScopedManager

from .knowledge_document import KnowledgeDocument
from .knowledge_source import KnowledgeSource


class KnowledgeChunk(models.Model):
    """
    A retrievable text chunk — the grain the AI agent queries with ILIKE.

    `id` is deterministic: uuid5(document.stable_id, f"{heading_path}|{ordinal}"),
    set in logic.py before save. Re-parsing the same text yields the same
    chunk ids, which keeps any future citations / embeddings stable across
    refreshes.
    """

    id = models.UUIDField(primary_key=True, editable=False)  # set by logic.py via deterministic uuid5
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    source = models.ForeignKey(KnowledgeSource, on_delete=models.CASCADE, related_name="chunks")
    document = models.ForeignKey(KnowledgeDocument, on_delete=models.CASCADE, related_name="chunks")

    # Best-effort section path, e.g. "Getting started > Installation". Empty
    # for Stage 1 plain text where we don't extract headings.
    heading_path = models.CharField(max_length=1024, blank=True, default="")
    # 0-based position within (document, heading_path). Combined with the
    # document stable_id, it seeds the deterministic chunk id.
    ordinal = models.IntegerField()
    content = models.TextField()
    # Rough character length; kept separately so the agent can ORDER BY / LIMIT
    # without loading content into HogQL context.
    char_count = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TeamScopedManager()

    class Meta:
        db_table = "posthog_business_knowledge_knowledgechunk"
        indexes = [
            models.Index(fields=["team", "source"], name="bk_chunk_team_source"),
            models.Index(fields=["document", "ordinal"], name="bk_chunk_doc_ordinal"),
            GinIndex(fields=["content"], opclasses=["gin_trgm_ops"], name="bk_chunk_content_trgm"),
        ]
        # One physical chunk per (document, heading_path, ordinal). Matches
        # the uuid5 seed so the deterministic id can never collide silently.
        constraints = [
            models.UniqueConstraint(
                fields=["document", "heading_path", "ordinal"],
                name="bk_chunk_unique_position",
            ),
        ]

    def save(self, *args: object, **kwargs: object) -> None:
        if self.pk is None:
            raise ValueError(
                "KnowledgeChunk.id must be set before save — use logic.py's deterministic chunk_id() to compute it."
            )
        super().save(*args, **kwargs)
