from collections.abc import Callable
from typing import Any

from posthog.temporal.common.base import PostHogWorkflow

from .activities import stop_cloud_agent_runs_over_quota_activity
from .workflows import StopCloudAgentRunsOverQuotaWorkflow

WORKFLOWS: list[type[PostHogWorkflow]] = [StopCloudAgentRunsOverQuotaWorkflow]
ACTIVITIES: list[Callable[..., Any]] = [stop_cloud_agent_runs_over_quota_activity]

__all__ = ["ACTIVITIES", "WORKFLOWS"]
