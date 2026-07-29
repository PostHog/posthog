"""Evaluation summary generation, routed through the internal Go ai-gateway when
configured, else the Python LLM gateway.

Large evaluations use a concurrent hierarchical map-reduce because one LLM call over all
runs can trip the ai-gateway's ~30s hard timeout.
"""

import json
import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any, Literal, TypeVar, cast

import structlog
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel
from redis.exceptions import LockError
from rest_framework import exceptions

from posthog import redis as posthog_redis
from posthog.llm.gateway_client import build_async_openai_client

from ..constants import (
    EVALUATION_SUMMARY_CHUNK_SIZE,
    EVALUATION_SUMMARY_GENERATION_LOCK_TIMEOUT_SECONDS,
    EVALUATION_SUMMARY_MAP_REASONING_MAX_CHARS,
    EVALUATION_SUMMARY_MAX_CONCURRENT_MAP_CALLS,
    EVALUATION_SUMMARY_MIN_USER_PROMPT_CHARS,
    EVALUATION_SUMMARY_PROMPT_MAX_CHARS,
    EVALUATION_SUMMARY_REDUCE_MAX_CANDIDATES_PER_RESULT,
    SUMMARIZATION_TIMEOUT,
)
from ..models import OpenAIModel
from ..utils import load_summarization_template
from .evaluation_schema import (
    EvaluationPatternCandidate,
    EvaluationSummaryMapResponse,
    EvaluationSummaryResponse,
    EvaluationSummaryStatistics,
)

logger = structlog.get_logger(__name__)

StructuredResponse = TypeVar("StructuredResponse", bound=BaseModel)
ResultCategory = Literal["pass", "fail", "na"]


@contextlib.asynccontextmanager
async def _team_generation_lock(team_id: int) -> AsyncIterator[None]:
    lock = posthog_redis.get_async_client().lock(
        f"llm_eval_summary_generation_lock:{team_id}",
        timeout=EVALUATION_SUMMARY_GENERATION_LOCK_TIMEOUT_SECONDS,
        blocking=False,
    )
    if not await lock.acquire(blocking=False):
        raise exceptions.Throttled(
            detail="An evaluation summary is already being generated for this project. Try again when it finishes."
        )

    try:
        yield
    finally:
        try:
            await lock.release()
        except LockError:
            logger.warning("evaluation_summary_generation_lock_release_failed", team_id=team_id)


def _result_label(result: bool | None) -> str:
    if result is None:
        return "N/A"
    return "PASS" if result else "FAIL"


def _result_category(result: bool | None) -> ResultCategory:
    if result is None:
        return "na"
    return "pass" if result else "fail"


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


def _available_user_prompt_chars(system_prompt: str) -> int:
    available_characters = EVALUATION_SUMMARY_PROMPT_MAX_CHARS - len(system_prompt)
    if available_characters < EVALUATION_SUMMARY_MIN_USER_PROMPT_CHARS:
        raise exceptions.ValidationError(
            "The evaluation context is too long to summarize. Shorten the evaluation prompt or description and try again."
        )
    return available_characters


def _prompt_fits(system_prompt: str, user_prompt: str) -> bool:
    return len(system_prompt) + len(user_prompt) <= EVALUATION_SUMMARY_PROMPT_MAX_CHARS


def _truncate_reasoning(reasoning: str) -> str:
    if len(reasoning) <= EVALUATION_SUMMARY_MAP_REASONING_MAX_CHARS:
        return reasoning

    marker = "\n...[truncated]...\n"
    available_characters = EVALUATION_SUMMARY_MAP_REASONING_MAX_CHARS - len(marker)
    prefix_length = (available_characters + 1) // 2
    suffix_length = available_characters // 2
    return f"{reasoning[:prefix_length]}{marker}{reasoning[-suffix_length:]}"


def _build_bounded_chunks(evaluation_runs: list[dict], max_prompt_chars: int) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    current_chunk: list[dict] = []

    for run in evaluation_runs:
        bounded_run = {**run, "reasoning": _truncate_reasoning(run["reasoning"])}
        proposed_chunk = [*current_chunk, bounded_run]
        proposed_prompt = _build_runs_prompt(proposed_chunk)

        if current_chunk and (
            len(proposed_chunk) > EVALUATION_SUMMARY_CHUNK_SIZE or len(proposed_prompt) > max_prompt_chars
        ):
            chunks.append(current_chunk)
            current_chunk = [bounded_run]
        else:
            current_chunk = proposed_chunk

        if len(_build_runs_prompt(current_chunk)) > max_prompt_chars:
            raise exceptions.ValidationError(
                "An evaluation result is too long to summarize. Shorten its reasoning and try again."
            )

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _map_response_schema(max_candidates: int, max_occurrences: int) -> dict[str, Any]:
    schema = EvaluationSummaryMapResponse.model_json_schema()
    schema["properties"]["patterns"]["maxItems"] = max_candidates
    schema["$defs"]["EvaluationPatternCandidate"]["properties"]["occurrence_count"]["maximum"] = max_occurrences
    return schema


def _candidate_counts(candidates: list[EvaluationPatternCandidate]) -> dict[str, int]:
    counts = {"pass": 0, "fail": 0, "na": 0}
    for candidate in candidates:
        counts[candidate.result] += candidate.occurrence_count
    return counts


def _run_counts(evaluation_runs: list[dict]) -> dict[str, int]:
    statistics = _compute_statistics(evaluation_runs)
    return {
        "pass": statistics.pass_count,
        "fail": statistics.fail_count,
        "na": statistics.na_count,
    }


def _validate_map_response(response: EvaluationSummaryMapResponse, evaluation_runs: list[dict]) -> None:
    expected_counts = _run_counts(evaluation_runs)
    actual_counts = _candidate_counts(response.patterns)
    if actual_counts != expected_counts:
        raise ValueError(f"candidate counts {actual_counts} do not match run counts {expected_counts}")

    generation_results = {run["generation_id"]: _result_category(run["result"]) for run in evaluation_runs}
    if any(
        generation_results.get(generation_id) != candidate.result
        for candidate in response.patterns
        for generation_id in candidate.example_generation_ids
    ):
        raise ValueError("candidate response contains a generation ID from the wrong result category")


def _validate_reduce_response(
    response: EvaluationSummaryMapResponse, input_candidates: list[EvaluationPatternCandidate]
) -> None:
    input_counts = _candidate_counts(input_candidates)
    output_counts = _candidate_counts(response.patterns)
    if output_counts != input_counts:
        raise ValueError("reduced candidate counts do not match the input counts")

    generation_results = {
        generation_id: candidate.result
        for candidate in input_candidates
        for generation_id in candidate.example_generation_ids
    }
    if any(
        generation_results.get(generation_id) != candidate.result
        for candidate in response.patterns
        for generation_id in candidate.example_generation_ids
    ):
        raise ValueError("reduced response contains a generation ID from the wrong result category")


def _build_candidates_prompt(
    candidates: list[EvaluationPatternCandidate], statistics: EvaluationSummaryStatistics
) -> str:
    candidate_payload = json.dumps(
        [candidate.model_dump() for candidate in candidates],
        separators=(",", ":"),
    )
    return f"""Ground-truth statistics for the complete evaluation:
{statistics.model_dump_json()}

Candidate themes to consolidate:
{candidate_payload}"""


def _build_bounded_candidate_groups(
    candidates: list[EvaluationPatternCandidate],
    statistics: EvaluationSummaryStatistics,
    max_prompt_chars: int,
) -> list[list[EvaluationPatternCandidate]]:
    groups: list[list[EvaluationPatternCandidate]] = []
    current_group: list[EvaluationPatternCandidate] = []

    for candidate in candidates:
        proposed_group = [*current_group, candidate]
        if current_group and len(_build_candidates_prompt(proposed_group, statistics)) > max_prompt_chars:
            groups.append(current_group)
            current_group = [candidate]
        else:
            current_group = proposed_group

        if len(_build_candidates_prompt(current_group, statistics)) > max_prompt_chars:
            raise exceptions.APIException(
                "Couldn't fit evaluation evidence within the summary prompt limit. Reduce the number of runs and try again."
            )

    if current_group:
        groups.append(current_group)

    return groups


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


async def _run_map_completion(
    client: AsyncOpenAI,
    model: OpenAIModel,
    system_prompt: str,
    evaluation_runs: list[dict],
    team_id: int,
    user_distinct_id: str,
) -> EvaluationSummaryMapResponse:
    last_error: ValueError | None = None
    for attempt in range(2):
        response = await _run_structured_completion(
            client=client,
            model=model,
            system_prompt=system_prompt,
            user_prompt=_build_runs_prompt(evaluation_runs),
            team_id=team_id,
            user_distinct_id=user_distinct_id,
            response_model=EvaluationSummaryMapResponse,
            schema_name="evaluation_summary_candidates",
            response_schema=_map_response_schema(
                max_candidates=len(evaluation_runs),
                max_occurrences=len(evaluation_runs),
            ),
        )
        try:
            _validate_map_response(response, evaluation_runs)
            return response
        except ValueError as error:
            last_error = error
            logger.warning(
                "evaluation_summary_map_response_invalid",
                team_id=team_id,
                model=str(model),
                attempt=attempt + 1,
                error=str(error),
            )

    raise exceptions.APIException("Couldn't generate a complete evaluation summary. Try again.") from last_error


async def _run_reduce_completion(
    client: AsyncOpenAI,
    model: OpenAIModel,
    system_prompt: str,
    input_candidates: list[EvaluationPatternCandidate],
    statistics: EvaluationSummaryStatistics,
    team_id: int,
    user_distinct_id: str,
) -> EvaluationSummaryMapResponse:
    result_category_count = sum(count > 0 for count in _candidate_counts(input_candidates).values())
    max_candidates = min(
        EVALUATION_SUMMARY_REDUCE_MAX_CANDIDATES_PER_RESULT * result_category_count,
        max(result_category_count, len(input_candidates) - 1),
    )
    max_occurrences = sum(candidate.occurrence_count for candidate in input_candidates)
    last_error: ValueError | None = None

    for attempt in range(2):
        response = await _run_structured_completion(
            client=client,
            model=model,
            system_prompt=system_prompt,
            user_prompt=_build_candidates_prompt(input_candidates, statistics),
            team_id=team_id,
            user_distinct_id=user_distinct_id,
            response_model=EvaluationSummaryMapResponse,
            schema_name="evaluation_summary_reduced_candidates",
            response_schema=_map_response_schema(
                max_candidates=max_candidates,
                max_occurrences=max_occurrences,
            ),
        )
        try:
            _validate_reduce_response(response, input_candidates)
            return response
        except ValueError as error:
            last_error = error
            logger.warning(
                "evaluation_summary_reduce_response_invalid",
                team_id=team_id,
                model=str(model),
                attempt=attempt + 1,
                error=str(error),
            )

    raise exceptions.APIException("Couldn't consolidate the evaluation summary. Try again.") from last_error


async def _reduce_candidates_to_budget(
    client: AsyncOpenAI,
    model: OpenAIModel,
    candidates: list[EvaluationPatternCandidate],
    statistics: EvaluationSummaryStatistics,
    final_system_prompt: str,
    prompt_context: dict[str, Any],
    team_id: int,
    user_distinct_id: str,
    llm_call_semaphore: asyncio.Semaphore,
) -> list[EvaluationPatternCandidate]:
    final_user_prompt_chars = _available_user_prompt_chars(final_system_prompt)
    reduce_system_prompt = load_summarization_template(
        "prompts/evaluation_summary_reduce.djt",
        {
            **prompt_context,
            "max_candidates_per_result": EVALUATION_SUMMARY_REDUCE_MAX_CANDIDATES_PER_RESULT,
        },
    )
    reduce_user_prompt_chars = _available_user_prompt_chars(reduce_system_prompt)
    reduced_candidates = candidates

    while len(_build_candidates_prompt(reduced_candidates, statistics)) > final_user_prompt_chars:
        groups = _build_bounded_candidate_groups(
            reduced_candidates,
            statistics,
            reduce_user_prompt_chars,
        )

        async def reduce_group(group: list[EvaluationPatternCandidate]) -> EvaluationSummaryMapResponse:
            if len(group) == 1:
                return EvaluationSummaryMapResponse(patterns=group)
            async with llm_call_semaphore:
                return await _run_reduce_completion(
                    client=client,
                    model=model,
                    system_prompt=reduce_system_prompt,
                    input_candidates=group,
                    statistics=statistics,
                    team_id=team_id,
                    user_distinct_id=user_distinct_id,
                )

        reduced_groups = await asyncio.gather(*(reduce_group(group) for group in groups))
        next_candidates = [candidate for group in reduced_groups for candidate in group.patterns]
        if len(next_candidates) >= len(reduced_candidates):
            raise exceptions.APIException(
                "Couldn't reduce the evaluation evidence enough to generate a summary. Reduce the number of runs and try again."
            )
        reduced_candidates = next_candidates

    return reduced_candidates


async def _merge_summaries(
    client: AsyncOpenAI,
    model: OpenAIModel,
    batch_candidates: list[EvaluationSummaryMapResponse],
    statistics: EvaluationSummaryStatistics,
    prompt_context: dict[str, Any],
    team_id: int,
    user_distinct_id: str,
    llm_call_semaphore: asyncio.Semaphore,
) -> EvaluationSummaryResponse:
    merge_system_prompt = load_summarization_template("prompts/evaluation_summary_merge.djt", prompt_context)
    candidates = [candidate for batch in batch_candidates for candidate in batch.patterns]
    candidates = await _reduce_candidates_to_budget(
        client=client,
        model=model,
        candidates=candidates,
        statistics=statistics,
        final_system_prompt=merge_system_prompt,
        prompt_context=prompt_context,
        team_id=team_id,
        user_distinct_id=user_distinct_id,
        llm_call_semaphore=llm_call_semaphore,
    )
    merge_user_prompt = _build_candidates_prompt(candidates, statistics)

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


async def _generate_evaluation_summary(
    evaluation_runs: list[dict],
    team_id: int,
    model: OpenAIModel,
    filter_type: str,
    evaluation_name: str,
    evaluation_description: str,
    evaluation_prompt: str,
    user_distinct_id: str,
) -> EvaluationSummaryResponse:
    statistics = _compute_statistics(evaluation_runs)
    prompt_context = {
        "filter": filter_type,
        "evaluation_name": evaluation_name,
        "evaluation_description": evaluation_description,
        "evaluation_prompt": evaluation_prompt,
        "max_candidates": EVALUATION_SUMMARY_CHUNK_SIZE,
    }
    client = build_async_openai_client("llma_eval_summary", ai_product="aio_eval_summary")
    if len(evaluation_runs) <= EVALUATION_SUMMARY_CHUNK_SIZE:
        single_system_prompt = load_summarization_template("prompts/evaluation_summary.djt", prompt_context)
        single_user_prompt = _build_runs_prompt(evaluation_runs)
        if _prompt_fits(single_system_prompt, single_user_prompt):
            summary = await _run_structured_completion(
                client=client,
                model=model,
                system_prompt=single_system_prompt,
                user_prompt=single_user_prompt,
                team_id=team_id,
                user_distinct_id=user_distinct_id,
                response_model=EvaluationSummaryResponse,
                schema_name="evaluation_summary",
            )
            summary.statistics = statistics
            return summary

    map_system_prompt = load_summarization_template("prompts/evaluation_summary_map.djt", prompt_context)
    chunks = _build_bounded_chunks(
        evaluation_runs,
        max_prompt_chars=_available_user_prompt_chars(map_system_prompt),
    )
    llm_call_semaphore = asyncio.Semaphore(EVALUATION_SUMMARY_MAX_CONCURRENT_MAP_CALLS)

    async def summarize_chunk(chunk: list[dict]) -> EvaluationSummaryMapResponse:
        async with llm_call_semaphore:
            return await _run_map_completion(
                client=client,
                model=model,
                system_prompt=map_system_prompt,
                evaluation_runs=chunk,
                team_id=team_id,
                user_distinct_id=user_distinct_id,
            )

    batch_candidates = list(await asyncio.gather(*(summarize_chunk(chunk) for chunk in chunks)))
    summary = await _merge_summaries(
        client=client,
        model=model,
        batch_candidates=batch_candidates,
        statistics=statistics,
        prompt_context=prompt_context,
        team_id=team_id,
        user_distinct_id=user_distinct_id,
        llm_call_semaphore=llm_call_semaphore,
    )
    summary.statistics = statistics
    return summary


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

    Runs are summarized in a single call when small. Larger sets use bounded map
    calls and hierarchical reduction so each request stays below the prompt limit.

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

    try:
        async with _team_generation_lock(team_id):
            return await _generate_evaluation_summary(
                evaluation_runs=evaluation_runs,
                team_id=team_id,
                model=model,
                filter_type=filter_type,
                evaluation_name=evaluation_name,
                evaluation_description=evaluation_description,
                evaluation_prompt=evaluation_prompt,
                user_distinct_id=user_distinct_id,
            )
    except exceptions.APIException:
        raise
    except Exception as error:
        logger.exception("evaluation_summary_failed", team_id=team_id, model=str(model), error=str(error))
        raise exceptions.APIException("Failed to generate evaluation summary") from error
