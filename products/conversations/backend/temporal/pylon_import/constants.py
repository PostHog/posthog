"""Constants for Pylon historical import."""

from __future__ import annotations

BATCH_SIZE = 50
# Pylon allows 120 requests a minute to the messages endpoint for the whole organization, and
# every issue needs at least one. More parallel batches would only wait on the same allowance.
MAX_CONCURRENT_BATCH_WORKFLOWS = 2
CONTINUE_AS_NEW_AFTER_PAGES = 50

WORKFLOW_ID_PREFIX = "pylon-import"
BATCH_WORKFLOW_ID_PREFIX = "pylon-import-batch"
