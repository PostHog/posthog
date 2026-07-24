"""Temporal workflow and activities for the PostHog Telegram bot.

Runs on ``settings.TASKS_TASK_QUEUE`` alongside the Slack app workflows.
"""

from posthog.temporal.ai.telegram_app.activities import (
    cascade_telegram_repository_activity,
    classify_telegram_task_needs_repo_activity,
    create_telegram_task_activity,
    enforce_telegram_billing_quota_activity,
    post_telegram_reply_activity,
)
from posthog.temporal.ai.telegram_app.types import TelegramAppMentionWorkflowInputs
from posthog.temporal.ai.telegram_app.workflow import TelegramAppMentionWorkflow

TELEGRAM_APP_WORKFLOWS = [TelegramAppMentionWorkflow]

TELEGRAM_APP_ACTIVITIES = [
    cascade_telegram_repository_activity,
    classify_telegram_task_needs_repo_activity,
    create_telegram_task_activity,
    enforce_telegram_billing_quota_activity,
    post_telegram_reply_activity,
]

__all__ = [
    "TELEGRAM_APP_ACTIVITIES",
    "TELEGRAM_APP_WORKFLOWS",
    "TelegramAppMentionWorkflow",
    "TelegramAppMentionWorkflowInputs",
]
