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
