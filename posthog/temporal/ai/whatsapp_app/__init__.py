"""Temporal workflow and activities for the PostHog WhatsApp bot.

Runs on ``settings.TASKS_TASK_QUEUE`` alongside the Slack app and Telegram workflows.
"""

from posthog.temporal.ai.whatsapp_app.activities import (
    cascade_whatsapp_repository_activity,
    classify_whatsapp_task_needs_repo_activity,
    create_whatsapp_task_activity,
    enforce_whatsapp_billing_quota_activity,
    post_whatsapp_reply_activity,
)
from posthog.temporal.ai.whatsapp_app.types import WhatsAppAppMentionWorkflowInputs
from posthog.temporal.ai.whatsapp_app.workflow import WhatsAppAppMentionWorkflow

WHATSAPP_APP_WORKFLOWS = [WhatsAppAppMentionWorkflow]

WHATSAPP_APP_ACTIVITIES = [
    cascade_whatsapp_repository_activity,
    classify_whatsapp_task_needs_repo_activity,
    create_whatsapp_task_activity,
    enforce_whatsapp_billing_quota_activity,
    post_whatsapp_reply_activity,
]

__all__ = [
    "WHATSAPP_APP_ACTIVITIES",
    "WHATSAPP_APP_WORKFLOWS",
    "WhatsAppAppMentionWorkflow",
    "WhatsAppAppMentionWorkflowInputs",
]
