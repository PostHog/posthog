"""Read a pull request's Trunk merge queue state from the comment Trunk keeps on it.

Trunk publishes no check run. It posts one comment per pull request and edits that comment in place
through the whole lifecycle, so the comment is the only record of the queue state on GitHub.
Trunk's `trunk-*` status labels are not a substitute: Trunk applies them only sometimes, and merged
pull requests keep stale ones.
"""

import re
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any

_TRUNK_LOGIN = "trunk-io[bot]"
_QUEUE_COMMENT_MARKER = "<!-- Trunk Merge -->"
_TEST_ANALYTICS_MARKER = "<!-- Trunk Test Analytics -->"
_CHECKBOX_START = "<!-- Start PR Submit Checkbox -->"
_CHECKBOX_END = "<!-- End PR Submit Checkbox -->"
# The path segment matters: Trunk's flaky-test comment on the same pull request links to
# `/flaky-tests/` and is full of the word "failed".
_QUEUE_LINK_HOST = "app.trunk.io"
_QUEUE_LINK_PATH = "/merge-queue/"


class MergeQueueState(StrEnum):
    NOT_SUBMITTED = "not_submitted"
    # Trunk has the submission but waits for branch protection before it adds the pull request.
    NOT_READY = "not_ready"
    QUEUED = "queued"
    TESTING = "testing"
    PASSED = "passed"
    # A required check failed in the batch, but Trunk still has the pull request and waits for the
    # pull requests ahead of it, because one of them can be the real cause.
    PENDING_FAILURE = "pending_failure"
    FAILED = "failed"
    EJECTED = "ejected"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    MERGED = "merged"
    # Trunk's comment exists but its wording matches no known state. It counts as holding, because
    # a push into an unknown state can eject the pull request.
    UNKNOWN = "unknown"

    @property
    def holds_pull_request(self) -> bool:
        """Trunk has the pull request. A person submitted it, so it ships as it is."""
        return self in _HOLDING_STATES

    @property
    def push_would_eject(self) -> bool:
        """A push removes the pull request from the queue and resets every pull request testing behind it.

        `NOT_READY` is not here. Nothing tests the pull request yet, and Trunk waits for exactly the
        branch protection that a fix push can satisfy.
        """
        return self in _PUSH_EJECTS_STATES

    @classmethod
    def from_comments(cls, comments: Iterable[Mapping[str, Any]]) -> "MergeQueueState | None":
        """The state in the last Trunk queue comment, or None when Trunk does not manage the pull request.

        Takes GitHub REST issue comments. The last queue comment decides, because a recreated comment
        replaces the older one, and an older comment's state is stale.
        """
        last_body: str | None = None
        for comment in comments:
            body = comment.get("body")
            if isinstance(body, str) and _is_queue_comment(body, comment.get("user")):
                last_body = body
        return None if last_body is None else cls._from_body(last_body)

    @classmethod
    def _from_body(cls, body: str) -> "MergeQueueState":
        for pattern, state in _STATUS_PATTERNS:
            if pattern.search(body):
                return state
        # No status sentence means the comment is still the submit instruction, so the checkbox
        # is the whole answer.
        start = body.find(_CHECKBOX_START)
        if start == -1:
            return cls.UNKNOWN
        end = body.find(_CHECKBOX_END, start)
        checkbox = body[start + len(_CHECKBOX_START) : end if end != -1 else None]
        if re.search(r"\[x\]", checkbox, re.IGNORECASE):
            return cls.QUEUED
        if re.search(r"\[\s*\]", checkbox):
            return cls.NOT_SUBMITTED
        return cls.UNKNOWN


_HOLDING_STATES = frozenset(
    {
        MergeQueueState.NOT_READY,
        MergeQueueState.QUEUED,
        MergeQueueState.TESTING,
        MergeQueueState.PASSED,
        MergeQueueState.PENDING_FAILURE,
        MergeQueueState.UNKNOWN,
    }
)
_PUSH_EJECTS_STATES = _HOLDING_STATES - {MergeQueueState.NOT_READY}

# Trunk's status sentences, most decisive first. The order matters. Every removal shares the
# "removed from the merge queue" prefix, so each known reason must match before the bare prefix.
# Several states where Trunk still has the pull request mention a failure, so they must match
# before the bare failure sentence.
_STATUS_PATTERNS: tuple[tuple[re.Pattern[str], MergeQueueState], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), state)
    for pattern, state in (
        (r"merged successfully", MergeQueueState.MERGED),
        (r"was merged into .* as part of stacked pr", MergeQueueState.MERGED),
        (r"removed from the merge queue because it failed tests", MergeQueueState.FAILED),
        (r"waiting to become mergeable for too long", MergeQueueState.EJECTED),
        (r"removed from the merge queue because it was pushed to", MergeQueueState.EJECTED),
        (r"removed from the merge queue", MergeQueueState.CANCELLED),
        (r"could not start testing", MergeQueueState.FAILED),
        (r"waiting for other pull requests to finish testing", MergeQueueState.PENDING_FAILURE),
        (r"will be merged soon", MergeQueueState.PASSED),
        (r"will re-enter the queue|re-entering the merge queue", MergeQueueState.QUEUED),
        (r"running tests on this (pull request|stack)", MergeQueueState.TESTING),
        (r"waiting to start tests|waiting for tests to start", MergeQueueState.QUEUED),
        (r"is queued for merge as part of", MergeQueueState.QUEUED),
        (r"has failed|failed tests", MergeQueueState.FAILED),
        (r"submitted to merge", MergeQueueState.NOT_READY),
        # Trunk appends this to the instruction when GitHub sees the pull request as part of a
        # stack, so it must match before the checkbox, which stays ticked while nothing happens.
        (r"unable to merge this pr", MergeQueueState.REJECTED),
    )
)


def _is_queue_comment(body: str, user: object) -> bool:
    # Anyone can comment on a public pull request, so a lookalike account that posts Trunk's
    # wording must not change the state a bot pushes on.
    if not isinstance(user, Mapping) or user.get("login") != _TRUNK_LOGIN or user.get("type") != "Bot":
        return False
    if _TEST_ANALYTICS_MARKER in body:
        return False
    return (
        _QUEUE_COMMENT_MARKER in body
        or _CHECKBOX_START in body
        or (_QUEUE_LINK_HOST in body and _QUEUE_LINK_PATH in body)
    )
