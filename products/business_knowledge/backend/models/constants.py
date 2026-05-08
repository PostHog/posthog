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
