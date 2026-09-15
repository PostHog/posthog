from django.conf import settings

from products.alerts.backend.facade.contracts import SourceCycleBinding, SourceKind


def source_cycle_bindings() -> tuple[SourceCycleBinding, ...]:
    """The sources the orchestrator starts a cycle for on each tick.

    Every source shares the evaluation queue. A source moves to its own fleet by changing
    its `task_queue` here and deploying a worker that polls it. The orchestrator reads the
    queue from the binding, so that move does not touch the tick.

    Settings are read on each call rather than at import, matching the queue reads in
    `workflows.py`: the workflow sandbox blocks a module-level read from being refreshed.
    """
    return (
        SourceCycleBinding(
            source_kind=SourceKind.LOGS,
            workflow_name="logs-alert-source-cycle",
            task_queue=settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE,
        ),
    )
