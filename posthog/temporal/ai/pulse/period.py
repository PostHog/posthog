"""Deterministic period keys for Pulse scans — find-or-create digests per (team, period)."""

import datetime as dt

from posthog.models.pulse import PulseSubscriptionFrequency


def period_key(now: dt.datetime, frequency: PulseSubscriptionFrequency | str) -> str:
    """Stable identifier for the scan period containing `now`.

    Weekly -> ISO week ("2026-W22"); daily -> date ("2026-05-29"). Used as the
    idempotency key so re-runs and Temporal retries reuse one digest per period.
    Caller passes a deterministic clock (`workflow.now()`) inside workflows.
    """
    if frequency == PulseSubscriptionFrequency.DAILY:
        return now.date().isoformat()
    iso_year, iso_week, _ = now.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def period_bounds(now: dt.datetime, frequency: PulseSubscriptionFrequency | str) -> tuple[dt.datetime, dt.datetime]:
    """(`period_start`, `period_end`) for the digest. End is `now`; start is one period back."""
    span = dt.timedelta(days=1) if frequency == PulseSubscriptionFrequency.DAILY else dt.timedelta(days=7)
    return now - span, now
