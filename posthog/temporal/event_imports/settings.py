from posthog.temporal.event_imports.external_event_job import (
    ExternalEventJobWorkflow,
    fetch_amplitude_data_activity,
    uncompress_file_activity,
    process_events_activity,
)

# comment

WORKFLOWS = [ExternalEventJobWorkflow]

ACTIVITIES = [
    fetch_amplitude_data_activity,
    uncompress_file_activity,
    process_events_activity,
]
