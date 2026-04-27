import dagster

from products.error_tracking.dags import spike_event_cleanup, symbol_set_cleanup

from . import resources

defs = dagster.Definitions(
    assets=[
        symbol_set_cleanup.symbol_sets_to_delete,
        symbol_set_cleanup.symbol_set_cleanup_results,
        spike_event_cleanup.spike_events_cleanup,
    ],
    jobs=[
        symbol_set_cleanup.symbol_set_cleanup_job,
        spike_event_cleanup.spike_event_cleanup_job,
    ],
    schedules=[
        symbol_set_cleanup.daily_symbol_set_cleanup_schedule,
        spike_event_cleanup.daily_spike_event_cleanup_schedule,
    ],
    resources=resources,
)
