import datetime

from django.db import models


class SourceType(models.TextChoices):
    TEXT = "text", "Text"
    # Reserved for Stage 2 / Stage 3 — declared up front so the DB choice
    # set is stable and we don't need a migration to widen it later.
    URL = "url", "URL"
    FILE = "file", "File"


class SourceStatus(models.TextChoices):
    # Stage 1 text sources jump straight to READY inside the create
    # endpoint. PENDING / PROCESSING / ERROR exist for Stage 2+ async flows.
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready"
    ERROR = "error", "Error"


class RefreshStatus(models.TextChoices):
    """
    Outcome of the last refresh attempt on a URL source. Decoupled from
    `SourceStatus` because we want to keep a source `READY` even if the
    latest refresh returned `NOT_MODIFIED` or `ERROR` — the old chunks are
    still serving queries.
    """

    SUCCESS = "success", "Success"
    NOT_MODIFIED = "not_modified", "Not modified"
    ERROR = "error", "Error"


class CrawlMode(models.TextChoices):
    """
    How to expand a URL source into documents.

    - SINGLE: Stage 2a behavior — exactly one doc per source.
    - SITEMAP: fetch sitemap.xml(+index) from the entry URL, treat listed
      URLs as documents.
    - SAME_ORIGIN: BFS from the entry URL up to `max_depth`, staying on the
      same (scheme, host, port). Respects robots.txt.
    - GITHUB_REPO: reserved — landed later so existing rows don't need a
      migration when we add it.
    """

    SINGLE = "single", "Single page"
    SITEMAP = "sitemap", "Sitemap"
    SAME_ORIGIN = "same_origin", "Same origin crawl"
    GITHUB_REPO = "github_repo", "GitHub repository"


class RefreshInterval(models.TextChoices):
    """
    How often a URL source is re-fetched by the background coordinator.

    `manual` (the default) means "never auto-refresh — only on explicit
    'Refresh now'". The coordinator runs hourly, so `1h` is the finest
    achievable cadence; finer granularity would need per-source schedules.
    """

    MANUAL = "manual", "Manual only"
    HOURLY = "1h", "Every hour"
    SIX_HOURLY = "6h", "Every 6 hours"
    DAILY = "24h", "Every day"
    WEEKLY = "7d", "Every week"


# Maps every non-manual interval to its concrete duration. `manual` is
# deliberately absent — callers treat "not in this dict" as "don't auto-refresh".
REFRESH_INTERVAL_TIMEDELTAS: dict[str, datetime.timedelta] = {
    RefreshInterval.HOURLY: datetime.timedelta(hours=1),
    RefreshInterval.SIX_HOURLY: datetime.timedelta(hours=6),
    RefreshInterval.DAILY: datetime.timedelta(days=1),
    RefreshInterval.WEEKLY: datetime.timedelta(days=7),
}


class EmbeddingStatus(models.TextChoices):
    """
    API-only (not a DB column): semantic-index state of a source, derived
    from its documents. A `ready` source serves keyword (FTS) search right
    away, but semantic search needs the hourly coordinator to classify and
    embed its documents — `pending` covers that window. `disabled` means the
    org has not approved AI data processing, so embeddings never run.
    """

    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    DISABLED = "disabled", "Disabled"


class GapStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    DISMISSED = "dismissed", "Dismissed"


class SafetyVerdict(models.TextChoices):
    """
    Content-safety classification of a document, set by the background
    classifier. New / content-changed docs start `unknown` and are
    classified on the next coordinator pass. Only `safe` docs are
    included in agent search (fail-closed: `unknown` is excluded until
    the classifier runs).
    """

    UNKNOWN = "unknown", "Unknown"
    SAFE = "safe", "Safe"
    UNSAFE = "unsafe", "Unsafe"
