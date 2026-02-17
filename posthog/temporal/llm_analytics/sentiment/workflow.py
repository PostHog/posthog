"""Temporal workflow definition for sentiment classification."""

from datetime import timedelta
from typing import Any

import temporalio
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.sentiment.activities import classify_sentiment_activity
from posthog.temporal.llm_analytics.sentiment.constants import ACTIVITY_TIMEOUT_SECONDS, MAX_RETRY_ATTEMPTS
from posthog.temporal.llm_analytics.sentiment.schema import ClassifySentimentInput


@temporalio.workflow.defn(name="llma-sentiment-classify")
class ClassifySentimentWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ClassifySentimentInput:
        return ClassifySentimentInput(
            team_id=int(inputs[0]),
            trace_ids=inputs[1:],
        )

    @temporalio.workflow.run
    async def run(self, input: ClassifySentimentInput) -> dict[str, dict[str, Any]]:
        return await temporalio.workflow.execute_activity(
            classify_sentiment_activity,
            input,
            start_to_close_timeout=timedelta(seconds=ACTIVITY_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=MAX_RETRY_ATTEMPTS),
        )
