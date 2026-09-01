"""Parses the finalizer's run allowlist.

Its own module rather than living in ``finalize.py``: that module reaches ``posthog.tasks`` for the
Celery queue, which imports it back, so anything importing it early sits inside that cycle. The
parser has no dependencies at all, so both the finalizer and the operator tooling can read it.
"""

from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)


def parse_run_allowlist(raw: str) -> frozenset[UUID] | None:
    """The runs the finalizer may stamp. ``None`` means every run, an empty set means none.

    Grammar mirrors ``realtime_teams._team_in_allowlist``: empty / ``all`` / ``*`` match everything,
    ``none`` matches nothing, otherwise a whitespace-tolerant comma list. Two deliberate departures,
    both because a readiness stamp cannot be undone. Ids compare as parsed ``UUID``s, so an
    unhyphenated or uppercase id from a pasted line still matches rather than silently matching
    nothing. And a non-keyword value whose every token was malformed matches nothing rather than
    everything: a typo in a restriction must not widen it to the whole fleet.
    """
    raw = raw.strip()
    if raw == "" or raw.lower() == "all" or raw == "*":
        return None
    if raw.lower() == "none":
        return frozenset()

    allowed: set[UUID] = set()
    malformed: list[str] = []
    for part in (segment.strip() for segment in raw.split(",")):
        if not part:
            continue
        try:
            allowed.add(UUID(part))
        except ValueError:
            malformed.append(part)
    if malformed:
        logger.error("cohort_backfill_finalizer_allowlist_malformed_tokens", tokens=malformed)
    return frozenset(allowed)
