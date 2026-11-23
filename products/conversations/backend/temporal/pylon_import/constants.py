"""Constants for Pylon historical import."""

from __future__ import annotations

# A batch commits only at its end, so a retry or an activity timeout repeats the whole batch
# while the timed-out thread keeps running. A small batch bounds that repeated work and keeps
# even an issue-heavy batch well inside the activity timeout.
BATCH_SIZE = 10
# Pylon allows 120 requests a minute to the messages endpoint for the whole organization, and
# every issue needs at least one. More parallel batches would only wait on the same allowance.
MAX_CONCURRENT_BATCH_WORKFLOWS = 2
CONTINUE_AS_NEW_AFTER_PAGES = 50

WORKFLOW_ID_PREFIX = "pylon-import"
BATCH_WORKFLOW_ID_PREFIX = "pylon-import-batch"
