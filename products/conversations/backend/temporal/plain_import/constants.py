"""Constants for Plain historical import."""

from __future__ import annotations

BATCH_SIZE = 50
MAX_CONCURRENT_BATCH_WORKFLOWS = 5
CONTINUE_AS_NEW_AFTER_PAGES = 50

WORKFLOW_ID_PREFIX = "plain-import"
BATCH_WORKFLOW_ID_PREFIX = "plain-import-batch"

THREADS_PER_PAGE = 100
TIMELINE_ENTRIES_PER_PAGE = 50

MESSAGE_ENTRY_TYPES = [
    "EMAIL",
    "CHAT",
    "SLACK_MESSAGE",
    "SLACK_REPLY",
    "MS_TEAMS_MESSAGE",
    "DISCORD_MESSAGE",
    "NOTE",
    "CUSTOM",
]

REGION_HOSTS: dict[str, str] = {
    "uk": "core-api.uk.plain.com",
    "us": "core-api.us.plain.com",
}
