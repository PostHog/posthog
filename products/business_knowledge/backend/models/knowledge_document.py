from django.db import models

from posthog.models.utils import UUIDModel

from .knowledge_source import KnowledgeSource


class KnowledgeDocument(UUIDModel):
    """
    One parsed artifact inside a KnowledgeSource. Stage 1 text sources have
    exactly one document per source; Stage 2/3 URL/file sources can have many.
    """

    # team_id is denormalized off source.team_id so every HogQL-exposed table
    # can be filtered independently without forcing a join.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    source = models.ForeignKey(KnowledgeSource, on_delete=models.CASCADE, related_name="documents")
    # Stable identity across refreshes. For Stage 1 text it's the document's
    # own UUID. For Stage 2+ URLs it will be set to the normalized URL so a
    # re-crawl replaces rather than duplicates.
    stable_id = models.CharField(max_length=512)
    title = models.CharField(max_length=512, blank=True, default="")
    # The raw parsed text. Kept so we can re-chunk without re-parsing the
    # source. Bounded by MAX_TEXT_SIZE_BYTES at the API layer.
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_business_knowledge_knowledgedocument"
        indexes = [
            models.Index(fields=["team", "source"], name="bk_doc_team_source"),
            models.Index(fields=["source"], name="bk_doc_source"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["source", "stable_id"], name="bk_doc_unique_per_source"),
        ]
