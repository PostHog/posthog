from django.db import models

from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.utils import UUIDModel

from .constants import SafetyVerdict
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
    stable_id = models.CharField(max_length=2048)
    title = models.CharField(max_length=512, blank=True, default="")
    # The raw parsed text. Kept so we can re-chunk without re-parsing the
    # source. Bounded by MAX_TEXT_SIZE_BYTES at the API layer.
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- Stage 2a: URL-document fields ---
    # Absolute fetched URL (after any redirects). For Stage 2a this mirrors
    # `source.source_url`; Stage 2b crawl makes them diverge.
    url = models.URLField(max_length=2048, blank=True, default="")
    # Per-document ETag — deliberately separate from `source.last_etag` so
    # the crawl case can use per-page conditional GETs later.
    etag = models.CharField(max_length=255, blank=True, default="")
    # sha256 of the parsed text we stored in `content`. Lets us skip
    # re-chunking when a refresh returns new HTML but semantically identical
    # content (common with news/CMS templates).
    content_hash = models.CharField(max_length=64, blank=True, default="")
    # Set when a crawl stops seeing a page that used to exist. Stage 2a
    # never writes this; kept as a forward-compatible field so Stage 2b
    # doesn't need another migration.
    tombstoned_at = models.DateTimeField(null=True, blank=True)

    # --- Stage 5: content-safety classification ---
    # `unknown` until the background classifier runs. Reset to `unknown`
    # whenever content changes so only new/changed docs get re-classified.
    safety_verdict = models.CharField(max_length=16, choices=SafetyVerdict.choices, default=SafetyVerdict.UNKNOWN)
    # Human-facing one-liner explaining an `unsafe` verdict. Empty otherwise.
    safety_reason = models.TextField(blank=True, default="")
    # How many coordinator passes have tried (and failed) to get a verdict for
    # this doc. The classifier fails CLOSED on a model block/error/timeout —
    # the doc stays `unknown` (excluded from search) rather than being waved
    # through as `safe`. Without a bound, the coordinator would re-pick those
    # docs every pass forever; once this hits CLASSIFY_MAX_ATTEMPTS we stop
    # re-queuing (the doc stays excluded). Reset to 0 whenever content changes.
    classification_attempts = models.PositiveSmallIntegerField(default=0, db_default=0)

    # When this doc's chunks were last produced to the embedding pipeline
    # (Kafka -> worker -> ClickHouse `document_embeddings`). NULL means "not yet
    # embedded" — the coordinator's embedding pass picks those up. Only ever
    # stamped for a SAFE doc whose produce succeeded; reset to NULL whenever
    # content changes (so the new content re-embeds) or when reconciliation
    # finds the vectors never landed in ClickHouse. "Emitted" means produced to
    # Kafka, not confirmed-present in ClickHouse — see logic.emit_pending_embeddings.
    embeddings_emitted_at = models.DateTimeField(null=True, blank=True)

    objects = TeamScopedManager()

    class Meta:
        db_table = "posthog_business_knowledge_knowledgedocument"
        indexes = [
            models.Index(fields=["team", "source"], name="bk_doc_team_source"),
            models.Index(fields=["source"], name="bk_doc_source"),
            # Cross-team scan for docs awaiting safety classification. Partial on
            # `unknown` (the only value ever queried) so it shrinks to ~0 rows in
            # steady state — far smaller/faster than a full 3-value btree.
            models.Index(
                fields=["tombstoned_at"],
                name="bk_doc_pending_classify",
                condition=models.Q(safety_verdict=SafetyVerdict.UNKNOWN),
            ),
            # Cross-team scan for the tombstone hard-delete sweep.
            models.Index(fields=["tombstoned_at"], name="bk_doc_tombstoned"),
            # Backs the cross-team embedding passes. Partial on `safe` (the only
            # verdict that's ever embedded) so it tracks just the embeddable
            # working set. Serves BOTH the pending scan (`embeddings_emitted_at
            # IS NULL`, NULLs clustered in the btree) and the reconciliation
            # scan (`embeddings_emitted_at < cutoff ORDER BY ASC`).
            models.Index(
                fields=["embeddings_emitted_at"],
                name="bk_doc_embed_state",
                condition=models.Q(safety_verdict=SafetyVerdict.SAFE),
            ),
        ]
        constraints = [
            models.UniqueConstraint(fields=["source", "stable_id"], name="bk_doc_unique_per_source"),
        ]

    def __str__(self) -> str:
        return self.title or self.stable_id
