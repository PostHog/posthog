from posthog.temporal.event_screenshots.activities import (
    load_event_sessions,
    load_event_types,
    store_event_screenshot,
    take_event_screenshot,
)
from posthog.temporal.event_screenshots.workflows import GenerateEventScreenshotsWorkflow

WORKFLOWS = [
    GenerateEventScreenshotsWorkflow,
]

ACTIVITIES = [
    load_event_types,
    load_event_sessions,
    take_event_screenshot,
    store_event_screenshot,
]
