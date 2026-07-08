"""Constants for Zendesk historical import."""

from __future__ import annotations

BATCH_SIZE = 100
MAX_CONCURRENT_BATCH_WORKFLOWS = 5
CONTINUE_AS_NEW_AFTER_PAGES = 50

WORKFLOW_ID_PREFIX = "zendesk-import"
BATCH_WORKFLOW_ID_PREFIX = "zendesk-import-batch"
