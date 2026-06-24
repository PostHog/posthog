from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from .constants import CrawlMode, RefreshInterval, RefreshStatus, SourceStatus, SourceType


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
    # --- Stage 5: background refresh cadence ---
    # How often the coordinator re-fetches this source. `manual` = never
    # auto-refresh. Only meaningful for URL sources; text/file ignore it.
    refresh_interval = models.CharField(max_length=16, choices=RefreshInterval.choices, default=RefreshInterval.MANUAL)

    # --- Stage 2b: multi-page crawl fields ---
    # How to expand `source_url` into N documents. `single` keeps Stage 2a
    # semantics (one doc per source); other modes run the discover pipeline.
    crawl_mode = models.CharField(max_length=16, choices=CrawlMode.choices, blank=True, default=CrawlMode.SINGLE)
    # Free-form knobs for the crawl: `include_globs`, `exclude_globs`,
    # `max_depth`, `max_pages`. Stored as JSON so adding a knob doesn't
    # require a migration. Validated at the serializer layer; logic.py
    # re-reads with safe defaults.
    crawl_config = models.JSONField(default=dict, blank=True)

    # --- Always-on context ---
    # When True, all SAFE/READY chunks from this source are injected into every
    # support reply prompt (tone, policies, company direction) without requiring
    # a query match. Same safety gate as search — fails closed until classified.
    always_include = models.BooleanField(default=False)

    # --- Stage 3: file-source metadata (all nullable — additive) ---
    # Sanitized original filename from the upload. Never used as a path.
    original_filename = models.CharField(max_length=255, blank=True, default="")
    # Content type detected from magic bytes, not from the upload header.
    file_content_type = models.CharField(max_length=128, blank=True, default="")
    # Size of the uploaded file in bytes (compressed, as received).
    file_size_bytes = models.PositiveIntegerField(null=True, blank=True)

    objects = TeamScopedManager()

    class Meta:
        db_table = "posthog_business_knowledge_knowledgesource"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["team", "-created_at"], name="bk_source_team_created"),
            models.Index(fields=["team", "status"], name="bk_source_team_status"),
            models.Index(fields=["team", "source_type"], name="bk_source_team_type"),
            # Cross-team due-source scan by the background refresh coordinator.
            models.Index(fields=["refresh_interval", "last_refresh_at"], name="bk_source_refresh_due"),
            # Fast lookup for always-on context injection (only flagged sources).
            models.Index(fields=["team"], condition=models.Q(always_include=True), name="bk_source_always_include"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.source_type})"
