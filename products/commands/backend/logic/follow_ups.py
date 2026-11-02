"""Remembers where a command's result goes, for work that finishes after the command answered.

The first answer only says that the work started. When the product reports the outcome, the
receivers in ``receivers.py`` look up the follow-up and send the result there. The channel decides
the address: a Slack command answers in its thread, and a pull request comment needs none, because
the work posts its result on the pull request itself.

The record lives in the cache with a time limit, so a lost record only loses the follow-up message.
"""

from typing import Any

from django.core.cache import cache

import structlog

from posthog.dataclasses import frozen

from .commands import FollowUpAddress

logger = structlog.get_logger(__name__)

# Longer than any review or QA run takes.
_TTL_SECONDS = 24 * 60 * 60


@frozen
class FollowUp:
    address: FollowUpAddress
    subject_label: str
    subject_url: str

    def to_payload(self) -> dict[str, Any]:
        return {"address": dict(self.address), "subject_label": self.subject_label, "subject_url": self.subject_url}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "FollowUp":
        return cls(
            address=dict(payload["address"]),
            subject_label=str(payload["subject_label"]),
            subject_url=str(payload["subject_url"]),
        )


def stamphog_run_key(run_id: str) -> str:
    return f"commands:follow_up:stamphog_run:{run_id}"


def review_key(project_id: int, repository: str, number: int, review_mode: str) -> str:
    # A request can wait behind a running turn of the other mode, and the head can move while it
    # waits, so the mode names the turn and the head does not. Each project reviews on its own.
    return f"commands:follow_up:review:{project_id}:{repository.lower()}#{number}:{review_mode}"


def task_run_key(run_id: str) -> str:
    return f"commands:follow_up:task_run:{run_id}"


def remember(key: str, follow_up: FollowUp) -> None:
    """Saves the follow-up next to any other request that waits for the same outcome."""
    try:
        waiting = cache.get(key) or []
        cache.set(key, [*waiting, follow_up.to_payload()], timeout=_TTL_SECONDS)
    except Exception:
        # The command already started its work. Only the follow-up message is lost.
        logger.warning("command_follow_up_not_saved", key=key, exc_info=True)


def take(key: str) -> list[FollowUp]:
    """The follow-ups saved under ``key``, once. A retried or repeated outcome gets none."""
    try:
        waiting = cache.get(key)
        # The delete decides between two callers that read the same outcome at once.
        if not waiting or not cache.delete(key):
            return []
        return [FollowUp.from_payload(payload) for payload in waiting]
    except Exception:
        logger.warning("command_follow_up_not_read", key=key, exc_info=True)
        return []
