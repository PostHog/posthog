from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from .constants import RefreshStatus, SourceStatus, SourceType


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

    # --- Stage 2a: URL-source fields (all nullable — additive, text sources
    # leave them empty) ---
    # Canonical submitted URL (after SSRF validation and userinfo strip).
    # Stage 2b will widen this into a multi-page crawl; for now it's the
    # single URL we fetched.
    source_url = models.URLField(max_length=2048, blank=True, default="")
    # Last time we successfully reached out to `source_url` (regardless of
    # whether content actually changed).
    last_refresh_at = models.DateTimeField(null=True, blank=True)
    last_refresh_status = models.CharField(max_length=16, choices=RefreshStatus.choices, blank=True, default="")
    # Human-facing failure reason from the most recent refresh attempt. Kept
    # separate from `error_message` because refresh failures don't knock the
    # source out of READY — old chunks keep serving.
    last_refresh_error = models.TextField(blank=True, default="")
    # Last ETag received; fed back via `If-None-Match` on the next refresh
    # to get cheap 304 responses. Not an index — we only look it up by source.
    last_etag = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "posthog_business_knowledge_knowledgesource"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["team", "-created_at"], name="bk_source_team_created"),
            models.Index(fields=["team", "source_type"], name="bk_source_team_type"),
        ]
