from posthog.temporal.waiter.workflow import WAITER, WaitWorkflow

WORKFLOWS = [WaitWorkflow]
ACTIVITIES = [WAITER.wait_for_activity, WAITER.wait_for_activity_sync]
