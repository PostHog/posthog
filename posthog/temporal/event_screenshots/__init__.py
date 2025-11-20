from posthog.temporal.event_screenshots.activities import load_event_sessions, load_event_types
from posthog.temporal.event_screenshots.workflows import GenerateEventScreenshotsWorkflow

WORKFLOWS = [
    GenerateEventScreenshotsWorkflow,
]

ACTIVITIES = [
    load_event_types,
    load_event_sessions,
]
