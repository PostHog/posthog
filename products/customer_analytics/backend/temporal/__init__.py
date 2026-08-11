from products.customer_analytics.backend.temporal.calendar_sync import (
    CalendarSyncCoordinatorWorkflow,
    CalendarSyncWorkflow,
    calendar_sync_collect_integrations_activity,
    calendar_sync_integration_activity,
)

WORKFLOWS = [CalendarSyncCoordinatorWorkflow, CalendarSyncWorkflow]
ACTIVITIES = [calendar_sync_collect_integrations_activity, calendar_sync_integration_activity]
