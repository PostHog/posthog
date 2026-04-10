from __future__ import annotations

import random
import threading

from django.conf import settings

_request_local = threading.local()


def use_personhog() -> bool:
    """Return whether to use personhog for the current operation.

    When called inside a pinned scope (e.g. HTTP request via middleware),
    the first call rolls the dice and all subsequent calls on the same
    thread reuse that decision — guaranteeing consistency within a request.

    Outside a pinned scope the decision is re-rolled every call (legacy behavior).
    """
    cached = getattr(_request_local, "personhog_decision", None)
    if cached is not None:
        return cached

    decision = _decide_personhog()

    if getattr(_request_local, "personhog_pinned", False):
        _request_local.personhog_decision = decision

    return decision


def _decide_personhog() -> bool:
    if not getattr(settings, "PERSONHOG_ENABLED", False):
        return False

    if not getattr(settings, "PERSONHOG_ADDR", ""):
        return False

    rollout_pct = getattr(settings, "PERSONHOG_ROLLOUT_PERCENTAGE", 0)

    if rollout_pct >= 100:
        return True
    if rollout_pct <= 0:
        return False

    return random.randint(1, 100) <= rollout_pct


def pin_personhog_decision() -> None:
    """Start caching the gate decision on this thread."""
    _request_local.personhog_pinned = True


def unpin_personhog_decision() -> None:
    """Clear the cached decision and stop caching."""
    _request_local.personhog_decision = None
    _request_local.personhog_pinned = False
