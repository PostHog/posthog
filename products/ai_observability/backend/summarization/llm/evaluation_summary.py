"""Evaluation summary generation, routed through the internal Go ai-gateway when
configured, else the Python LLM gateway.

Large evaluations are summarized as a concurrent map-reduce: a single LLM call over all
runs takes long enough to trip the ai-gateway's ~30s hard timeout, so runs are split into
chunks that are summarized concurrently and then merged, keeping every individual call
well under the cliff. See ``EVALUATION_SUMMARY_CHUNK_SIZE``.
"""

import asyncio
from typing import Any, cast

import structlog
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from rest_framework import exceptions

from posthog.llm.gateway_client import build_async_openai_client

from ..constants import EVALUATION_SUMMARY_CHUNK_SIZE, SUMMARIZATION_TIMEOUT
from ..models import OpenAIModel
from ..utils import load_summarization_template
from .evaluation_schema import EvaluationSummaryResponse, EvaluationSummaryStatistics

logger = structlog.get_logger(__name__)


def _result_label(result: bool | None) -> str:
    if result is None:
        return "N/A"
    return "PASS" if result else "FAIL"


def _compute_statistics(evaluation_runs: list[dict]) -> EvaluationSummaryStatistics:
    return EvaluationSummaryStatistics(
        total_analyzed=len(evaluation_runs),
        pass_count=sum(1 for run in evaluation_runs if run["result"] is True),
        fail_count=sum(1 for run in evaluation_runs if run["result"] is False),
        na_count=sum(1 for run in evaluation_runs if run["result"] is None),
    )


def _build_runs_prompt(evaluation_runs: list[dict]) -> str:
    """Format a set of evaluation runs into the user prompt fed to the LLM."""
    runs_text = "\n\n".join(
        f"- Generation ID: {run['generation_id']}\n  Result: {_result_label(run['result'])}\n  Reasoning: {run['reasoning']}"
        for run in evaluation_runs
    )

    stats = _compute_statistics(evaluation_runs)
    stats_parts = []
    if stats.pass_count > 0:
        stats_parts.append(f"{stats.pass_count} passed")
    if stats.fail_count > 0:
        stats_parts.append(f"{stats.fail_count} failed")
    if stats.na_count > 0:
        stats_parts.append(f"{stats.na_count} N/A")
    stats_text = ", ".join(stats_parts) if stats_parts else "no results"

    return f"""Analyze these {len(evaluation_runs)} evaluation results ({stats_text}):

{runs_text}"""


async def _run_structured_completion(
    client: AsyncOpenAI,
    model: OpenAIModel,
    system_prompt: str,
    user_prompt: str,
    team_id: int,
    user_distinct_id: str,
) -> EvaluationSummaryResponse:
    """Run one structured-output completion and validate it against the response schema."""
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    response = await client.chat.completions.create(
        model=str(model),
        messages=messages,
        user=user_distinct_id or "llma-evaluation-summarization",
        timeout=SUMMARIZATION_TIMEOUT,
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
        logger.error("evaluation_summary_empty_response", team_id=team_id, model=str(model))
        raise exceptions.APIException("Failed to generate evaluation summary: empty response")

    return EvaluationSummaryResponse.model_validate_json(content)


async def _merge_summaries(
    client: AsyncOpenAI,
    model: OpenAIModel,
    partial_summaries: list[EvaluationSummaryResponse],
    filter_type: str,
    evaluation_name: str,
    evaluation_description: str,
    evaluation_prompt: str,
    team_id: int,
    user_distinct_id: str,
) -> EvaluationSummaryResponse:
    """Consolidate per-chunk summaries into one final summary via a small LLM call."""
    merge_system_prompt = load_summarization_template(
        "prompts/evaluation_summary_merge.djt",
        {
            "filter": filter_type,
            "evaluation_name": evaluation_name,
            "evaluation_description": evaluation_description,
            "evaluation_prompt": evaluation_prompt,
        },
    )

    partials_json = "\n\n".join(
        f"### Batch {i + 1}\n{summary.model_dump_json(exclude={'statistics'}, indent=2)}"
        for i, summary in enumerate(partial_summaries)
    )
    merge_user_prompt = f"""Here are the {len(partial_summaries)} partial summaries to consolidate:

{partials_json}"""

    return await _run_structured_completion(
        client=client,
        model=model,
        system_prompt=merge_system_prompt,
        user_prompt=merge_user_prompt,
        team_id=team_id,
        user_distinct_id=user_distinct_id,
    )


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

    Runs are summarized in a single call when small; larger sets are split into
    concurrently-summarized chunks that are then merged, so no individual call risks the
    ai-gateway's ~30s timeout.

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

    system_prompt = load_summarization_template(
        "prompts/evaluation_summary.djt",
        {
            "filter": filter_type,
            "evaluation_name": evaluation_name,
            "evaluation_description": evaluation_description,
            "evaluation_prompt": evaluation_prompt,
        },
    )

    client = build_async_openai_client("llma_eval_summary", ai_product="aio_eval_summary")

    try:
        if len(evaluation_runs) <= EVALUATION_SUMMARY_CHUNK_SIZE:
            summary = await _run_structured_completion(
                client=client,
                model=model,
                system_prompt=system_prompt,
                user_prompt=_build_runs_prompt(evaluation_runs),
                team_id=team_id,
                user_distinct_id=user_distinct_id,
            )
        else:
            chunks = [
                evaluation_runs[i : i + EVALUATION_SUMMARY_CHUNK_SIZE]
                for i in range(0, len(evaluation_runs), EVALUATION_SUMMARY_CHUNK_SIZE)
            ]
            partial_summaries = await asyncio.gather(
                *(
                    _run_structured_completion(
                        client=client,
                        model=model,
                        system_prompt=system_prompt,
                        user_prompt=_build_runs_prompt(chunk),
                        team_id=team_id,
                        user_distinct_id=user_distinct_id,
                    )
                    for chunk in chunks
                )
            )
            summary = await _merge_summaries(
                client=client,
                model=model,
                partial_summaries=partial_summaries,
                filter_type=filter_type,
                evaluation_name=evaluation_name,
                evaluation_description=evaluation_description,
                evaluation_prompt=evaluation_prompt,
                team_id=team_id,
                user_distinct_id=user_distinct_id,
            )
    except exceptions.APIException:
        raise
    except Exception as e:
        logger.exception("evaluation_summary_failed", team_id=team_id, model=str(model), error=str(e))
        raise exceptions.APIException("Failed to generate evaluation summary") from e

    # Statistics are ground-truth counts over the full input, not LLM-generated.
    summary.statistics = _compute_statistics(evaluation_runs)
    return summary
