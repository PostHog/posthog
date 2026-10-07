"""Which sources evaluate for real, and how the dispatcher starts each one.

A source's evaluation lives in that source's product, so the dispatcher starts it by name
rather than by class. The alerts product imports nothing from a source.

A source absent from this map keeps the noop evaluation path.
"""

import datetime as dt

from django.conf import settings

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.logic.demand import DISCOVERY_LIMIT_PER_SOURCE


@frozen
class SourceBinding:
    workflow: str
    # The evaluation workflow runs here, and so does every activity it starts without naming a
    # queue. A source with slow checks gets its own queue, so it cannot hold the worker slots that
    # another source's checks need.
    task_queue: str
    # What an evaluation gets end to end: its reads, its write, and the delivery children it
    # starts. It has to hold every attempt a source's activities allow, because an attempt cut
    # off here is a batch that decided something and recorded nothing. Evaluations are abandoned
    # rather than awaited, so this does not have to fit inside the tick. It does hold the key for
    # its duration, which is what blocks a slow evaluation's own re-dispatch.
    evaluation_timeout: dt.timedelta
    # Batch keys one tick hands this source. Each key starts a workflow, so a source that admits
    # fewer checks than discovery finds would otherwise start workflows that return having done
    # nothing.
    discovery_limit: int

    def __post_init__(self) -> None:
        if self.discovery_limit < 1:
            raise ValueError("A source's discovery limit must be at least 1")


SOURCE_BINDINGS: dict[SourceKind, SourceBinding] = {
    SourceKind.LOGS: SourceBinding(
        workflow="logs-alert-evaluate",
        task_queue=settings.ALERTS_PLATFORM_EVALUATION_TASK_QUEUE,
        evaluation_timeout=dt.timedelta(seconds=75),
        discovery_limit=DISCOVERY_LIMIT_PER_SOURCE,
    ),
}


def source_evaluation_timeout(source: SourceKind) -> dt.timedelta:
    return SOURCE_BINDINGS[source].evaluation_timeout


def discovery_limits() -> dict[SourceKind, int]:
    return {source: binding.discovery_limit for source, binding in SOURCE_BINDINGS.items()}
