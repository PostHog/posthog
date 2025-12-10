import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .activities import (
    AICallsInput,
    CombineInput,
    ExtractInfoInput,
    MarkFailedInput,
    PromptsInput,
    SaveResultsInput,
    TopicsInput,
    combine_calls,
    extract_info_from_url,
    generate_prompts,
    get_topics,
    make_ai_calls,
    mark_run_failed,
    save_results,
)


@dataclass
class AIVisibilityWorkflowInput:
    domain: str
    run_id: str
    team_id: Optional[int] = None
    user_id: Optional[int] = None


@dataclass
class AIVisibilityWorkflowResult:
    domain: str
    combined: dict
    s3_path: str


@temporalio.workflow.defn(name="ai-visibility")
class AIVisibilityWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> AIVisibilityWorkflowInput:
        loaded = json.loads(inputs[0])
        return AIVisibilityWorkflowInput(
            domain=loaded["domain"],
            run_id=loaded["run_id"],
            team_id=loaded.get("team_id"),
            user_id=loaded.get("user_id"),
        )

    @temporalio.workflow.run
    async def run(self, input: AIVisibilityWorkflowInput) -> AIVisibilityWorkflowResult:
        try:
            info: dict = await workflow.execute_activity(
                extract_info_from_url,
                ExtractInfoInput(domain=input.domain),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            topics: list[dict] = await workflow.execute_activity(
                get_topics,
                TopicsInput(domain=input.domain, info=info),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            prompts: list[dict] = await workflow.execute_activity(
                generate_prompts,
                PromptsInput(domain=input.domain, topics=topics, info=info),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            ai_calls: list[dict] = await workflow.execute_activity(
                make_ai_calls,
                AICallsInput(domain=input.domain, prompts=prompts, info=info, topics=topics),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            combined: dict = await workflow.execute_activity(
                combine_calls,
                CombineInput(domain=input.domain, info=info, topics=topics, ai_calls=ai_calls),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            s3_path = await workflow.execute_activity(
                save_results,
                SaveResultsInput(run_id=input.run_id, combined=combined),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            return AIVisibilityWorkflowResult(domain=input.domain, combined=combined, s3_path=s3_path)
        except Exception as e:
            error_message = str(e)
            await workflow.execute_activity(
                mark_run_failed,
                MarkFailedInput(run_id=input.run_id, error_message=error_message),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise
