from collections.abc import Callable

from django.dispatch import Signal

# Sent with `team_id=` and `cohort_id=` once a realtime cohort's backfill readiness stamp commits, so
# other products react to it without the cohorts product importing them. A cohort that needs both
# kinds of backfill can still lack the other stamp, so a receiver checks readiness itself.
realtime_cohort_ready = Signal()


def connect_realtime_cohort_ready(receiver: Callable[..., object], *, dispatch_uid: str) -> None:
    """``receiver`` gets ``team_id=`` and ``cohort_id=`` after a readiness stamp commits. A receiver
    that raises is logged and never fails the finalizer."""
    realtime_cohort_ready.connect(receiver, dispatch_uid=dispatch_uid)
