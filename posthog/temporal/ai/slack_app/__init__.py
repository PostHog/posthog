"""Temporal activities for the PostHog Slack App.

Activities living here run on ``settings.MAX_AI_TASK_QUEUE`` and are imported
by ``posthog/temporal/ai/posthog_code_slack_mention.py`` at module load time.
The package is the long-term home for activity splits out of that file; this
PR ships the classifier and follow-ups will land here one PR at a time.
"""

from posthog.temporal.ai.slack_app.activities import (
    CLASSIFIER_THREAD_HISTORY_MESSAGES,
    classify_message_is_agent_directed,
    classify_untagged_followup_activity,
)
from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionWorkflowInputs

SLACK_APP_ACTIVITIES = [
    classify_untagged_followup_activity,
]

__all__ = [
    "CLASSIFIER_THREAD_HISTORY_MESSAGES",
    "PostHogCodeSlackMentionWorkflowInputs",
    "SLACK_APP_ACTIVITIES",
    "classify_message_is_agent_directed",
    "classify_untagged_followup_activity",
]
