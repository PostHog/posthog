"""Which scheduling backend each materialization lands on, and why.

Counting saved queries with a lingering `sync_frequency_interval` tells you a query sits on v1,
but not which branch put it there, and it cannot distinguish a team that is merely unmigrated
from a genuine regression. Recording the decision as it is made does both, so "are we still
minting v1 schedules where we shouldn't" is answerable without a Postgres sweep.
"""

from posthog.otel_metrics import OtelInstrumentFactory

_otel = OtelInstrumentFactory("data-modeling")

SCHEDULE_BACKEND_METRIC = "data_modeling.materialization.scheduled"


def record_schedule_backend(*, backend: str, reason: str) -> None:
    """Record one materialization against the backend chosen for it.

    `backend` is "v1" or "v2"; `reason` is which branch chose it. Both are closed sets, so the
    series count stays fixed. Deliberately carries no team id: which teams are on v1 is already
    a Postgres query, whereas the branch taken exists only at this moment.
    """
    _otel.counter(
        SCHEDULE_BACKEND_METRIC,
        description="Materializations by the scheduling backend chosen for them, and the reason",
    ).add(1, {"backend": backend, "reason": reason})
