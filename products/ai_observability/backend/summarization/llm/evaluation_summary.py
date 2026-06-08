"""LLM gateway-based evaluation summary generation."""

from typing import Any, cast

import structlog
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from rest_framework import exceptions

from posthog.llm.gateway_client import get_llm_client

from ..constants import SUMMARIZATION_TIMEOUT
from ..models import OpenAIModel
from ..utils import load_summarization_template
from .evaluation_schema import EvaluationSummaryResponse

logger = structlog.get_logger(__name__)


async def summarize_evaluation_runs(
    evaluation_runs: list[dict],
    team_id: int,
    model: OpenAIModel,
    filter_type: str = "all",
    evaluation_name: str = "",
    evaluation_description: str = "",
    evaluation_prompt: str = "",
    user_distinct_id: str = "",
) -> EvaluationSummaryResponse:
    """
    Generate summary of evaluation runs using LLM gateway with structured outputs.

    Args:
        evaluation_runs: List of dicts with 'generation_id' (str), 'result' (bool or None), and 'reasoning' (str)
        team_id: Team ID for logging and tracking
        model: OpenAI model to use
        filter_type: The filter applied ('all', 'pass', 'fail', 'na')
        evaluation_name: Name of the evaluation being summarized
        evaluation_description: Description of what the evaluation tests for
        evaluation_prompt: The prompt used by the LLM judge
        user_distinct_id: Distinct ID of the user for analytics tracking

    Returns:
        Structured evaluation summary response
    """
    if not evaluation_runs:
        raise exceptions.ValidationError("No evaluation runs provided")

    def result_label(result: bool | None) -> str:
        if result is None:
            return "N/A"
        return "PASS" if result else "FAIL"

    # Format the evaluation runs for the prompt (include generation_id so LLM can reference them)
    runs_text = "\n\n".join(
        [
            f"- Generation ID: {run['generation_id']}\n  Result: {result_label(run['result'])}\n  Reasoning: {run['reasoning']}"
            for run in evaluation_runs
        ]
    )

    # Count statistics for the prompt
    pass_count = sum(1 for run in evaluation_runs if run["result"] is True)
    fail_count = sum(1 for run in evaluation_runs if run["result"] is False)
    na_count = sum(1 for run in evaluation_runs if run["result"] is None)

    system_prompt = load_summarization_template(
        "prompts/evaluation_summary.djt",
        {
            "filter": filter_type,
            "evaluation_name": evaluation_name,
            "evaluation_description": evaluation_description,
            "evaluation_prompt": evaluation_prompt,
        },
    )
    stats_parts = []
    if pass_count > 0:
        stats_parts.append(f"{pass_count} passed")
    if fail_count > 0:
        stats_parts.append(f"{fail_count} failed")
    if na_count > 0:
        stats_parts.append(f"{na_count} N/A")
    stats_text = ", ".join(stats_parts) if stats_parts else "no results"

    user_prompt = f"""Analyze these {len(evaluation_runs)} evaluation results ({stats_text}):

{runs_text}"""

    sync_client = get_llm_client("llma_eval_summary")
    client = AsyncOpenAI(
        base_url=sync_client.base_url,
        api_key=sync_client.api_key,
        timeout=SUMMARIZATION_TIMEOUT,
    )

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = await client.chat.completions.create(
            model=str(model),
            messages=messages,
            user=user_distinct_id or "llma-evaluation-summarization",
            response_format=cast(
                Any,
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "evaluation_summary",
                        "strict": True,
                        "schema": EvaluationSummaryResponse.model_json_schema(),
                    },
                },
            ),
        )

        content = response.choices[0].message.content
        if not content:
            logger.error(
                "evaluation_summary_empty_response",
                team_id=team_id,
                model=str(model),
            )
            raise exceptions.APIException("Failed to generate evaluation summary: empty response")

        return EvaluationSummaryResponse.model_validate_json(content)

    except Exception as e:
        logger.exception(
            "evaluation_summary_failed",
            team_id=team_id,
            model=str(model),
            error=str(e),
        )
        raise exceptions.APIException("Failed to generate evaluation summary") from e
