from posthog.temporal.subscriptions.activities import (
    advance_next_delivery_date,
    create_delivery_record,
    create_export_assets,
    deliver_subscription,
    fetch_due_subscriptions_activity,
    update_delivery_record,
    validate_subscription_for_delivery,
)
from posthog.temporal.subscriptions.snapshot_activities import snapshot_subscription_insights
from posthog.temporal.subscriptions.workflows import (
    HandleSubscriptionValueChangeWorkflow,
    ProcessSubscriptionWorkflow,
    ScheduleAllSubscriptionsWorkflow,
)

WORKFLOWS = [ScheduleAllSubscriptionsWorkflow, HandleSubscriptionValueChangeWorkflow, ProcessSubscriptionWorkflow]

ACTIVITIES = [
    fetch_due_subscriptions_activity,
    validate_subscription_for_delivery,
    create_export_assets,
    deliver_subscription,
    advance_next_delivery_date,
    create_delivery_record,
    update_delivery_record,
    snapshot_subscription_insights,
]
