"""Which saves go to the frontier review, and when. A save that would have alerted queues one review per burst of
saves, and the verdict is remembered per function, so a parked probe or an unchanged function is not reviewed again.

The Django cache, which is Redis, holds both keys. Losing one costs one extra review, never a missed one.
"""

import json
import time
import hashlib
from dataclasses import asdict
from enum import StrEnum
from typing import Any

from django.core.cache import cache

from posthog.dataclasses import frozen

from products.cdp.backend.abuse import rules
from products.cdp.backend.abuse.classifier import HogFunctionContent

# A key in the `cdp-abuse-classifier` payload. The review runs only while it is true, and Jev keeps recording.
SWITCH = "frontier_review"
DEBOUNCE_SECONDS = 120
# A function saved again and again is still reviewed this long after the first save of the burst.
MAX_DELAY_SECONDS = 600
# A pending review expires this long after it is due. Its task normally removes it first, so only a lost task, for
# example to a worker restart, leaves it to expire, and the next save then starts a new burst.
LOST_TASK_SECONDS = 900
VERDICT_TTL_SECONDS = 30 * 24 * 60 * 60


class SkipReason(StrEnum):
    PARKED_TRUE_POSITIVE = "parked_true_positive"
    UNCHANGED = "unchanged"
    SWITCHED_OFF = "switched_off"


@frozen
class StoredVerdict:
    verdict: str
    parked: bool
    fingerprint: str
    reviewed_at: float


@frozen
class Pending:
    first_saved_at: float
    due_at: float


def pending_key(hog_function_id: str) -> str:
    return f"cdp_abuse:frontier:pending:{hog_function_id}"


def verdict_key(hog_function_id: str) -> str:
    return f"cdp_abuse:frontier:v1:{hog_function_id}"


def fingerprint(content: HogFunctionContent, rule_hits: tuple[rules.Rule, ...], outbound_call: bool) -> str:
    """What a reviewer's verdict rests on: the code, where each rule hit matched, and where requests go. Message
    text, filters and names stay out, so editing a chat message or a filter does not ask for another review."""
    evidence = sorted(
        (entry.rule.value, entry.location, entry.host or "", entry.request_target)
        for entry in rules.rule_evidence(content)
        if entry.rule in rule_hits
    )
    facts = {
        "code": content.hog,
        "rule_hits": sorted(rule.value for rule in rule_hits),
        "evidence": evidence,
        "request_hosts": sorted(rules.request_hosts(content)),
        "outbound_call": outbound_call,
    }
    return hashlib.sha256(json.dumps(facts, separators=(",", ":")).encode()).hexdigest()


def skip_reason(*, switched_on: bool, stored: StoredVerdict | None, fingerprint: str) -> SkipReason | None:
    if not switched_on:
        return SkipReason.SWITCHED_OFF
    if stored is None:
        return None
    if stored.parked:
        return SkipReason.PARKED_TRUE_POSITIVE
    return SkipReason.UNCHANGED if stored.fingerprint == fingerprint else None


def pushed_back(pending: Pending, now: float) -> Pending:
    """The pending review after another save of the burst."""
    due_at = min(now + DEBOUNCE_SECONDS, pending.first_saved_at + MAX_DELAY_SECONDS)
    return Pending(first_saved_at=pending.first_saved_at, due_at=due_at)


def seconds_to_wait(pending: Pending | None, now: float) -> float | None:
    """For the queued task: wait while the function is still being saved, or review now. A pending entry the cache
    lost reviews now too, and the stored verdict stops a second task from reviewing the same version again."""
    if pending is not None and pending.due_at > now:
        return pending.due_at - now
    return None


def stored_verdict(hog_function_id: str) -> StoredVerdict | None:
    return _read(StoredVerdict, cache.get(verdict_key(hog_function_id)))


def store_verdict(hog_function_id: str, *, verdict: str, parked: bool, fingerprint: str) -> None:
    stored = StoredVerdict(verdict=verdict, parked=parked, fingerprint=fingerprint, reviewed_at=time.time())
    cache.set(verdict_key(hog_function_id), _write(stored), VERDICT_TTL_SECONDS)


def pending_review(hog_function_id: str) -> Pending | None:
    return _read(Pending, cache.get(pending_key(hog_function_id)))


def start_or_push_back(hog_function_id: str) -> bool:
    """Push back the pending review of the function, or start one. True when this save started it, so it queues the
    task: `cache.add` lets only one of two concurrent saves start the burst."""
    now = time.time()
    pending = pending_review(hog_function_id)
    if pending is not None:
        _set_pending(hog_function_id, pushed_back(pending, now), now)
        return False
    started = Pending(first_saved_at=now, due_at=now + DEBOUNCE_SECONDS)
    return cache.add(pending_key(hog_function_id), _write(started), _pending_ttl(started, now))


def take_due_review(hog_function_id: str) -> float | None:
    """Seconds to wait, or None after removing the pending review, so the next save after this point starts a new
    burst."""
    wait = seconds_to_wait(pending_review(hog_function_id), time.time())
    if wait is None:
        cache.delete(pending_key(hog_function_id))
    return wait


def _set_pending(hog_function_id: str, pending: Pending, now: float) -> None:
    cache.set(pending_key(hog_function_id), _write(pending), _pending_ttl(pending, now))


def _pending_ttl(pending: Pending, now: float) -> int:
    return int(pending.due_at + LOST_TASK_SECONDS - now)


def _write(value: StoredVerdict | Pending) -> dict[str, Any]:
    # Plain dicts, so a worker on another release reads what this one wrote without unpickling a class.
    return asdict(value)


def _read[T: (StoredVerdict, Pending)](kind: type[T], raw: object) -> T | None:
    return kind(**raw) if isinstance(raw, dict) else None
