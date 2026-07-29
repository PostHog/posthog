"""Evaluation summary generation, routed through the internal Go ai-gateway when
configured, else the Python LLM gateway.

Large evaluations use a concurrent map-reduce: a single LLM call over all runs takes long
enough to trip the ai-gateway's ~30s hard timeout, so each chunk extracts counted candidate
themes and a final call merges them globally. See ``EVALUATION_SUMMARY_CHUNK_SIZE``.
"""

import asyncio
from typing import Any, TypeVar, cast

import structlog
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel
from rest_framework import exceptions

from posthog.llm.gateway_client import build_async_openai_client

from ..constants import (
    EVALUATION_SUMMARY_CHUNK_SIZE,
    EVALUATION_SUMMARY_MAP_PROMPT_MAX_CHARS,
    EVALUATION_SUMMARY_MAP_REASONING_MAX_CHARS,
    EVALUATION_SUMMARY_MAX_CONCURRENT_MAP_CALLS,
    SUMMARIZATION_TIMEOUT,
)
from ..models import OpenAIModel
from ..utils import load_summarization_template
from .evaluation_schema import EvaluationSummaryMapResponse, EvaluationSummaryResponse, EvaluationSummaryStatistics

logger = structlog.get_logger(__name__)

StructuredResponse = TypeVar("StructuredResponse", bound=BaseModel)


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


def _truncate_reasoning(reasoning: str) -> str:
    if len(reasoning) <= EVALUATION_SUMMARY_MAP_REASONING_MAX_CHARS:
        return reasoning

    marker = "\n...[truncated]...\n"
    available_characters = EVALUATION_SUMMARY_MAP_REASONING_MAX_CHARS - len(marker)
    prefix_length = (available_characters + 1) // 2
    suffix_length = available_characters // 2
    return f"{reasoning[:prefix_length]}{marker}{reasoning[-suffix_length:]}"


def _build_bounded_chunks(evaluation_runs: list[dict]) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    current_chunk: list[dict] = []

    for run in evaluation_runs:
        bounded_run = {**run, "reasoning": _truncate_reasoning(run["reasoning"])}
        proposed_chunk = [*current_chunk, bounded_run]
        proposed_prompt = _build_runs_prompt(proposed_chunk)

        if current_chunk and (
            len(proposed_chunk) > EVALUATION_SUMMARY_CHUNK_SIZE
            or len(proposed_prompt) > EVALUATION_SUMMARY_MAP_PROMPT_MAX_CHARS
        ):
            chunks.append(current_chunk)
            current_chunk = [bounded_run]
        else:
            current_chunk = proposed_chunk

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _map_response_schema(max_candidates: int) -> dict[str, Any]:
    schema = EvaluationSummaryMapResponse.model_json_schema()
    schema["properties"]["patterns"]["maxItems"] = max_candidates
    schema["$defs"]["EvaluationPatternCandidate"]["properties"]["occurrence_count"]["maximum"] = max_candidates
    return schema


async def _run_structured_completion(
    client: AsyncOpenAI,
    model: OpenAIModel,
    system_prompt: str,
    user_prompt: str,
    team_id: int,
    user_distinct_id: str,
    response_model: type[StructuredResponse],
    schema_name: str,
    response_schema: dict[str, Any] | None = None,
) -> StructuredResponse:
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
                    "name": schema_name,
                    "strict": True,
                    "schema": response_schema or response_model.model_json_schema(),
                },
            },
        ),
    )

    content = response.choices[0].message.content
    if not content:
        logger.error("evaluation_summary_empty_response", team_id=team_id, model=str(model))
        raise exceptions.APIException("Failed to generate evaluation summary: empty response")

    return response_model.model_validate_json(content)


async def _merge_summaries(
    client: AsyncOpenAI,
    model: OpenAIModel,
    batch_candidates: list[EvaluationSummaryMapResponse],
    chunk_sizes: list[int],
    statistics: EvaluationSummaryStatistics,
    filter_type: str,
    evaluation_name: str,
    evaluation_description: str,
    evaluation_prompt: str,
    team_id: int,
    user_distinct_id: str,
) -> EvaluationSummaryResponse:
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
        f"### Batch {i + 1} ({chunk_size} runs)\n{summary.model_dump_json(indent=2)}"
        for i, (summary, chunk_size) in enumerate(zip(batch_candidates, chunk_sizes, strict=True))
    )
    merge_user_prompt = f"""Ground-truth statistics for the complete evaluation:
{statistics.model_dump_json(indent=2)}

Here are candidate themes from {len(batch_candidates)} batches to consolidate:

{partials_json}"""

    return await _run_structured_completion(
        client=client,
        model=model,
        system_prompt=merge_system_prompt,
        user_prompt=merge_user_prompt,
        team_id=team_id,
        user_distinct_id=user_distinct_id,
        response_model=EvaluationSummaryResponse,
        schema_name="evaluation_summary",
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

    statistics = _compute_statistics(evaluation_runs)
    prompt_context = {
        "filter": filter_type,
        "evaluation_name": evaluation_name,
        "evaluation_description": evaluation_description,
        "evaluation_prompt": evaluation_prompt,
        "max_candidates": EVALUATION_SUMMARY_CHUNK_SIZE,
    }
    client = build_async_openai_client("llma_eval_summary", ai_product="aio_eval_summary")
    single_user_prompt = _build_runs_prompt(evaluation_runs)

    try:
        if (
            len(evaluation_runs) <= EVALUATION_SUMMARY_CHUNK_SIZE
            and len(single_user_prompt) <= EVALUATION_SUMMARY_MAP_PROMPT_MAX_CHARS
        ):
            system_prompt = load_summarization_template("prompts/evaluation_summary.djt", prompt_context)
            summary = await _run_structured_completion(
                client=client,
                model=model,
                system_prompt=system_prompt,
                user_prompt=single_user_prompt,
                team_id=team_id,
                user_distinct_id=user_distinct_id,
                response_model=EvaluationSummaryResponse,
                schema_name="evaluation_summary",
            )
        else:
            chunks = _build_bounded_chunks(evaluation_runs)
            map_system_prompt = load_summarization_template("prompts/evaluation_summary_map.djt", prompt_context)
            map_call_semaphore = asyncio.Semaphore(EVALUATION_SUMMARY_MAX_CONCURRENT_MAP_CALLS)

            async def summarize_chunk(chunk: list[dict]) -> EvaluationSummaryMapResponse:
                async with map_call_semaphore:
                    return await _run_structured_completion(
                        client=client,
                        model=model,
                        system_prompt=map_system_prompt,
                        user_prompt=_build_runs_prompt(chunk),
                        team_id=team_id,
                        user_distinct_id=user_distinct_id,
                        response_model=EvaluationSummaryMapResponse,
                        schema_name="evaluation_summary_candidates",
                        response_schema=_map_response_schema(len(chunk)),
                    )

            batch_candidates = list(await asyncio.gather(*(summarize_chunk(chunk) for chunk in chunks)))
            summary = await _merge_summaries(
                client=client,
                model=model,
                batch_candidates=batch_candidates,
                chunk_sizes=[len(chunk) for chunk in chunks],
                statistics=statistics,
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
    summary.statistics = statistics
    return summary
