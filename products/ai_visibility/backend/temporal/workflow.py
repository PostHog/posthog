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
    PromptsInput,
    TopicsInput,
    combine_calls,
    extract_info_from_url,
    generate_prompts,
    get_topics,
    make_ai_calls,
)


@dataclass
class AIVisibilityWorkflowInput:
    domain: str
    team_id: Optional[int] = None
    user_id: Optional[int] = None


@dataclass
class AIVisibilityWorkflowResult:
    domain: str
    combined: dict


@temporalio.workflow.defn(name="ai-visibility")
class AIVisibilityWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> AIVisibilityWorkflowInput:
        loaded = json.loads(inputs[0])
        return AIVisibilityWorkflowInput(
            domain=loaded["domain"],
            team_id=loaded.get("team_id"),
            user_id=loaded.get("user_id"),
        )

    @temporalio.workflow.run
    async def run(self, input: AIVisibilityWorkflowInput) -> AIVisibilityWorkflowResult:
        info = await workflow.execute_activity(
            extract_info_from_url,
            ExtractInfoInput(domain=input.domain),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        topics = await workflow.execute_activity(
            get_topics,
            TopicsInput(domain=input.domain, info=info),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        prompts = await workflow.execute_activity(
            generate_prompts,
            PromptsInput(domain=input.domain, topics=topics),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        ai_calls = await workflow.execute_activity(
            make_ai_calls,
            AICallsInput(domain=input.domain, prompts=prompts),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        combined = await workflow.execute_activity(
            combine_calls,
            CombineInput(domain=input.domain, info=info, topics=topics, ai_calls=ai_calls),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        return AIVisibilityWorkflowResult(domain=input.domain, combined=combined)
