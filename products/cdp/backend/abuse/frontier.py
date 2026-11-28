"""Which saves go to the frontier review, and when. A save that would have alerted queues one review per burst of
saves, and the verdict is remembered per function, so a parked probe or an unchanged function is not reviewed again.

The Django cache, which is Redis, holds the keys. A lost verdict key costs one extra review. A lost pending key
loses the review of that burst, and the next save that would alert starts a new one.
"""

import json
import time
import hashlib
from dataclasses import asdict, fields
from enum import StrEnum
from typing import Any

from django.conf import settings
from django.core.cache import cache

from posthog.dataclasses import frozen

from products.cdp.backend.abuse import rules
from products.cdp.backend.abuse.classifier import HogFunctionContent

# A key in the `cdp-abuse-classifier` payload. The review runs only while it is true, and Jev keeps recording.
SWITCH = "frontier_review"
DEBOUNCE_SECONDS = 120
# A function saved again and again is still reviewed this long after the first save of the burst.
MAX_DELAY_SECONDS = 600
# Kombu's default for the Redis broker. A worker killed while it holds a countdown message gets it back only after
# this, so the pending key has to outlive it, or the redelivered task finds nothing to claim.
_DEFAULT_BROKER_VISIBILITY_TIMEOUT_SECONDS = 3600
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


def pending_key(hog_function_id: str) -> str:
    return f"cdp_abuse:frontier:pending:{hog_function_id}"


def last_saved_key(hog_function_id: str) -> str:
    return f"cdp_abuse:frontier:last_saved:{hog_function_id}"


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


def skip_reason(*, stored: StoredVerdict | None, fingerprint: str) -> SkipReason | None:
    if stored is None:
        return None
    if stored.parked:
        return SkipReason.PARKED_TRUE_POSITIVE
    return SkipReason.UNCHANGED if stored.fingerprint == fingerprint else None


def _pending_ttl_seconds() -> int:
    transport = getattr(settings, "CELERY_BROKER_TRANSPORT_OPTIONS", None) or {}
    visibility = transport.get("visibility_timeout", _DEFAULT_BROKER_VISIBILITY_TIMEOUT_SECONDS)
    return MAX_DELAY_SECONDS + int(visibility) + DEBOUNCE_SECONDS


def due_at(first_saved_at: float, last_saved_at: float) -> float:
    """A burst is reviewed once the function has not been saved for the debounce, and at the latest at the cap."""
    return min(last_saved_at + DEBOUNCE_SECONDS, first_saved_at + MAX_DELAY_SECONDS)


def stored_verdict(hog_function_id: str) -> StoredVerdict | None:
    return _read(cache.get(verdict_key(hog_function_id)))


def store_verdict(hog_function_id: str, *, verdict: str, parked: bool, fingerprint: str) -> None:
    stored = StoredVerdict(verdict=verdict, parked=parked, fingerprint=fingerprint, reviewed_at=time.time())
    cache.set(verdict_key(hog_function_id), _write(stored), VERDICT_TTL_SECONDS)


def start_or_push_back(hog_function_id: str) -> bool:
    """Record this save in the burst. True when it started the burst, so it queues the task. A save never rewrites the
    pending key: `cache.add` lets only one save start a burst, and a save after the task claimed it starts a new one."""
    now = time.time()
    ttl = _pending_ttl_seconds()
    cache.set(last_saved_key(hog_function_id), now, ttl)
    if cache.add(pending_key(hog_function_id), now, ttl):
        return True
    # A burst still pending past its cap lost its task with no redelivery coming, so this save queues another one.
    first_saved_at = _number(cache.get(pending_key(hog_function_id)))
    return first_saved_at is not None and now > first_saved_at + MAX_DELAY_SECONDS + DEBOUNCE_SECONDS


def seconds_until_due(hog_function_id: str) -> float | None:
    """How long the queued task still waits, or None when the review is due or nothing is pending."""
    first_saved_at = _number(cache.get(pending_key(hog_function_id)))
    if first_saved_at is None:
        return None
    last_saved_at = _number(cache.get(last_saved_key(hog_function_id))) or first_saved_at
    wait = due_at(first_saved_at, last_saved_at) - time.time()
    return wait if wait > 0 else None


def claim_due_review(hog_function_id: str) -> bool:
    """Remove the due pending review, so the next save starts a new burst. Only the task whose delete removed the key
    reviews it, so two tasks of one burst never both review."""
    return cache.delete(pending_key(hog_function_id))


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _write(value: StoredVerdict) -> dict[str, Any]:
    # Plain dicts, so a worker on another release reads what this one wrote without unpickling a class.
    return asdict(value)


def _read(raw: object) -> StoredVerdict | None:
    # Unknown keys are dropped, so a field that a later release adds does not break this one during a deploy.
    if not isinstance(raw, dict):
        return None
    try:
        return StoredVerdict(**{field.name: raw[field.name] for field in fields(StoredVerdict) if field.name in raw})
    except TypeError:
        return None
