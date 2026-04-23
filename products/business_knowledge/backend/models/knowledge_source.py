from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from .constants import SourceStatus, SourceType


class KnowledgeSource(ModelActivityMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """
    A user-created collection of business knowledge (e.g. "Product docs",
    "Support macros"). One source groups one or more documents.
    """

    activity_logging_on_delete = True

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="business_knowledge_sources")
    name = models.CharField(max_length=255)
    source_type = models.CharField(max_length=16, choices=SourceType.choices)
    status = models.CharField(max_length=16, choices=SourceStatus.choices, default=SourceStatus.PENDING)
    # Human-facing failure reason. Empty when status != ERROR.
    error_message = models.TextField(blank=True, default="")

    class Meta:
        db_table = "posthog_business_knowledge_knowledgesource"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["team", "-created_at"], name="bk_source_team_created"),
            models.Index(fields=["team", "source_type"], name="bk_source_team_type"),
        ]
