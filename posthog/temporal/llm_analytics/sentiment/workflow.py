"""Temporal workflow definitions for sentiment classification."""

from datetime import timedelta
from typing import Any

import temporalio
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.sentiment.activities import classify_sentiment_batch_activity
from posthog.temporal.llm_analytics.sentiment.schema import ClassifySentimentBatchInput, ClassifySentimentInput


@temporalio.workflow.defn(name="llma-sentiment-classify-batch")
class ClassifySentimentBatchWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ClassifySentimentBatchInput:
        return ClassifySentimentBatchInput(
            team_id=int(inputs[0]),
            trace_ids=inputs[1:],
        )

    @temporalio.workflow.run
    async def run(self, input: ClassifySentimentBatchInput) -> dict[str, dict[str, Any]]:
        return await temporalio.workflow.execute_activity(
            classify_sentiment_batch_activity,
            input,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


@temporalio.workflow.defn(name="llma-sentiment-classify")
class ClassifySentimentWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ClassifySentimentInput:
        return ClassifySentimentInput(
            team_id=int(inputs[0]),
            trace_id=inputs[1],
        )

    @temporalio.workflow.run
    async def run(self, input: ClassifySentimentInput) -> dict[str, Any]:
        batch_input = ClassifySentimentBatchInput(
            team_id=input.team_id,
            trace_ids=[input.trace_id],
            date_from=input.date_from,
            date_to=input.date_to,
        )
        results = await temporalio.workflow.execute_activity(
            classify_sentiment_batch_activity,
            batch_input,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return results[input.trace_id]
