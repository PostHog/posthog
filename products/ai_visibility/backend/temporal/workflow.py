import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .activities import SaveResultsInput, save_results


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
        # TODO: Re-enable these steps after testing
        # info: dict = await workflow.execute_activity(
        #     extract_info_from_url,
        #     ExtractInfoInput(domain=input.domain),
        #     start_to_close_timeout=timedelta(seconds=30),
        #     retry_policy=RetryPolicy(maximum_attempts=3),
        # )
        #
        # topics: list[str] = await workflow.execute_activity(
        #     get_topics,
        #     TopicsInput(domain=input.domain, info=info),
        #     start_to_close_timeout=timedelta(seconds=30),
        #     retry_policy=RetryPolicy(maximum_attempts=3),
        # )
        #
        # prompts: list[dict] = await workflow.execute_activity(
        #     generate_prompts,
        #     PromptsInput(domain=input.domain, topics=topics, info=info),
        #     start_to_close_timeout=timedelta(seconds=30),
        #     retry_policy=RetryPolicy(maximum_attempts=3),
        # )
        #
        # ai_calls: list[dict] = await workflow.execute_activity(
        #     make_ai_calls,
        #     AICallsInput(domain=input.domain, prompts=prompts, info=info, topics=topics),
        #     start_to_close_timeout=timedelta(seconds=60),
        #     retry_policy=RetryPolicy(maximum_attempts=3),
        # )
        #
        # combined: dict = await workflow.execute_activity(
        #     combine_calls,
        #     CombineInput(domain=input.domain, info=info, topics=topics, ai_calls=ai_calls),
        #     start_to_close_timeout=timedelta(seconds=30),
        #     retry_policy=RetryPolicy(maximum_attempts=3),
        # )

        combined: dict = {
            "domain": input.domain,
            "summary": f"Mock AI visibility analysis for {input.domain}",
            "info": {"domain": input.domain, "description": f"Mock info for {input.domain}"},
            "topics": ["analytics", "product", "growth"],
            "ai_calls": [
                {"prompt": "What is this company about?", "result": "This is a mock result about the company."},
                {"prompt": "Who are their competitors?", "result": "Mock competitors analysis goes here."},
                {"prompt": "What is their pricing?", "result": "Mock pricing information."},
            ],
        }

        s3_path = await workflow.execute_activity(
            save_results,
            SaveResultsInput(run_id=input.run_id, combined=combined),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        return AIVisibilityWorkflowResult(domain=input.domain, combined=combined, s3_path=s3_path)
