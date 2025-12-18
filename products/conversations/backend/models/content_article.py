from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.utils import UUIDTModel

from .constants import Channel


class ContentArticle(UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    title = models.CharField(max_length=500)
    body = models.TextField()
    is_enabled = models.BooleanField(default=True)
    channels = ArrayField(
        models.CharField(max_length=20, choices=Channel.choices),
        default=list,
        blank=True,
        help_text="Channels where this article is available. Empty means all channels.",
    )
    embeddings = models.JSONField(
        null=True,
        blank=True,
        help_text="Vector embeddings of the article content for RAG semantic search.",
    )
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_content_articles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_content_article"
        indexes = [
            models.Index(fields=["team", "is_enabled"]),
        ]

    def __str__(self):
        return f"{self.title} ({'enabled' if self.is_enabled else 'disabled'})"
