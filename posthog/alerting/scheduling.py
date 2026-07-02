"""Django-side scheduling helpers for alert check sweeps.

The pure cadence math lives in common/alerting/scheduling.py; this module owns the
due-alert predicate every sweep's discover phase shares.
"""

from __future__ import annotations

from datetime import datetime

from django.db.models import Q


def due_alerts_q(now: datetime, *, broken_state: str, snoozed_state: str | None = None) -> Q:
    """Predicate for alerts due a check: enabled, `next_check_at` reached (or never
    set), not broken, and not actively snoozed.

    Snooze exclusion differs deliberately per product: logs parks snoozed alerts in
    a SNOOZED state and keeps evaluating them once `snooze_until` passes (pass
    `snoozed_state`); billing skips any alert with a future `snooze_until`
    regardless of state (leave `snoozed_state` unset).
    """
    q = Q(enabled=True) & (Q(next_check_at__lte=now) | Q(next_check_at__isnull=True)) & ~Q(state=broken_state)
    if snoozed_state is not None:
        q &= ~Q(state=snoozed_state, snooze_until__gt=now)
    else:
        q &= Q(snooze_until__isnull=True) | Q(snooze_until__lte=now)
    return q
