import json
import asyncio
import dataclasses
from datetime import datetime
from typing import Any

from django.conf import settings

import structlog
import posthoganalytics
from google.genai import types
from posthoganalytics.ai.gemini import AsyncClient, genai
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.event_usage import groups
from posthog.models import Organization, Team
from posthog.sync import database_sync_to_async
from posthog.temporal.data_imports.signals.registry import SignalEmitter, SignalEmitterOutput, SignalSourceTableConfig

from products.signals.backend.api import emit_signal

logger = structlog.get_logger(__name__)

# Default model to use for LLM calls
GEMINI_MODEL = "models/gemini-3-flash-preview"
# Concurrent LLM calls limit for actionability/summarization checks
LLM_CONCURRENCY_LIMIT = 20
# Concurrent workflow spawns for signal emission
EMIT_CONCURRENCY_LIMIT = 50
# Temporal gRPC payload size limit (2 MB)
TEMPORAL_PAYLOAD_MAX_BYTES = 2 * 1024 * 1024
# Maximum number of attempts for LLM calls (summarization & actionability)
LLM_MAX_ATTEMPTS = 3
# Per-call timeout for LLM requests (seconds)
LLM_CALL_TIMEOUT_SECONDS = 120
# Thinking budget for LLM calls (summarization & actionability are judgment tasks)
LLM_THINKING_BUDGET_TOKENS = 1024
# Backoff between LLM retry attempts (delay = initial * coefficient ^ (attempt - 1))
LLM_RETRY_INITIAL_DELAY_SECONDS = 5
LLM_RETRY_BACKOFF_COEFFICIENT = 2.0


def _capture_pipeline_stage(
    event: str,
    team: Team,
    organization: Organization,
    output: SignalEmitterOutput,
) -> None:
    try:
        posthoganalytics.capture(
            event=event,
            distinct_id=str(team.uuid),
            properties={
                "source_product": output.source_product,
                "source_type": output.source_type,
                "source_id": output.source_id,
            },
            groups=groups(organization, team),
        )
    except Exception:
        # Swallow the exception, to avoid breaking the flow over failed analytics event
        logger.exception(
            "Failed to capture signal pipeline stage event",
            event=event,
            source_product=output.source_product,
            source_type=output.source_type,
            source_id=output.source_id,
        )


def _safe_heartbeat() -> None:
    # Pipeline runs both inside Temporal activities (production) and standalone via the
    # emit_signals_from_fixture management command. Outside an activity context, heartbeat()
    # raises RuntimeError, so we no-op when there's nothing to report to.
    if activity.in_activity():
        activity.heartbeat()


def build_emitter_outputs(
    team_id: int,
    records: list[dict[str, Any]],
    emitter: SignalEmitter,
) -> tuple[list[SignalEmitterOutput], int]:
    outputs = []
    error_count = 0
    for record in records:
        try:
            output = emitter(team_id, record)
        except Exception:
            logger.exception(
                "Emitter failed for record, skipping",
                team_id=team_id,
                record=record,
                signals_type="data-import-signals",
            )
            error_count += 1
            continue
        if output is not None:
            # Avoid serializing datetime objects
            if output.extra:
                output = dataclasses.replace(
                    output,
                    extra={k: v.isoformat() if isinstance(v, datetime) else v for k, v in output.extra.items()},
                )
            outputs.append(output)
    return outputs, error_count


async def _summarize_description(
    client: AsyncClient,
    output: SignalEmitterOutput,
    summarization_prompt: str,
    threshold: int,
) -> SignalEmitterOutput:
    prompt_parts = [types.Part(text=summarization_prompt.format(description=output.description, max_length=threshold))]
    for attempt in range(LLM_MAX_ATTEMPTS):
        if attempt > 0:
            await asyncio.sleep(LLM_RETRY_INITIAL_DELAY_SECONDS * (LLM_RETRY_BACKOFF_COEFFICIENT ** (attempt - 1)))
        try:
            response = await asyncio.wait_for(
                client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt_parts,
                    config=types.GenerateContentConfig(
                        max_output_tokens=LLM_THINKING_BUDGET_TOKENS + max(threshold // 4, 256),
                        thinking_config=types.ThinkingConfig(
                            thinking_budget=LLM_THINKING_BUDGET_TOKENS,
                            include_thoughts=False,
                        ),
                    ),
                ),
                timeout=LLM_CALL_TIMEOUT_SECONDS,
            )
            if response.candidates and response.candidates[0].finish_reason == types.FinishReason.MAX_TOKENS:
                raise ValueError("LLM summary response was truncated due to token limit")
            summary = (response.text or "").strip()
            if not summary:
                raise ValueError("Empty response from LLM when summarizing description")
            if len(summary) > threshold:
                raise ValueError(f"Summary is {len(summary)} characters, must be at most {threshold}")
            return dataclasses.replace(output, description=summary)
        except Exception as e:
            posthoganalytics.capture_exception(
                e,
                properties={
                    "ai_product": "signals",
                    "tag": "signals_import",
                    "error_type": "summarization_failed",
                    "source_type": output.source_type,
                    "source_id": output.source_id,
                    "attempt": attempt + 1,
                },
            )
            prompt_parts.append(
                types.Part(
                    text=f"\n\nAttempt {attempt + 1} of {LLM_MAX_ATTEMPTS} to summarize description failed with error: {e!r}\nPlease fix your output."
                )
            )
    # Hard-truncate the description to the threshold if all attempts failed
    return dataclasses.replace(output, description=output.description[:threshold])


async def summarize_long_descriptions(
    outputs: list[SignalEmitterOutput],
    summarization_prompt: str,
    threshold: int,
    extra: dict[str, Any],
) -> list[SignalEmitterOutput]:
    needs_summary = [i for i, output in enumerate(outputs) if len(output.description) > threshold]
    if not needs_summary:
        return outputs
    client = genai.AsyncClient(api_key=settings.GEMINI_API_KEY)
    semaphore = asyncio.Semaphore(LLM_CONCURRENCY_LIMIT)
    _safe_heartbeat()
    completed_count = 0

    async def _bounded_summarize(output: SignalEmitterOutput) -> SignalEmitterOutput | None:
        nonlocal completed_count
        async with semaphore:
            try:
                result = await _summarize_description(client, output, summarization_prompt, threshold)
            except Exception:
                logger.exception(
                    "Summarization failed, skipping signal",
                    signal_source_id=output.source_id,
                    **extra,
                )
                return None
            finally:
                completed_count += 1
                if completed_count % LLM_CONCURRENCY_LIMIT == 0:
                    _safe_heartbeat()
            return result

    tasks: dict[int, asyncio.Task[SignalEmitterOutput | None]] = {}
    async with asyncio.TaskGroup() as tg:
        for i in needs_summary:
            tasks[i] = tg.create_task(_bounded_summarize(outputs[i]))
    result: list[SignalEmitterOutput] = []
    skipped = 0
    for i, output in enumerate(outputs):
        if i not in tasks:
            result.append(output)
        elif (summarized := tasks[i].result()) is not None:
            result.append(summarized)
        else:
            skipped += 1
    logger.info(
        f"Summarized {len(needs_summary) - skipped} long descriptions, skipped {skipped} (threshold={threshold})",
        signals_type="data-import-signals",
        **extra,
    )
    return result


def _extract_thoughts(response: types.GenerateContentResponse) -> str | None:
    if not response.candidates:
        return None
    content = response.candidates[0].content
    if content is None or content.parts is None:
        return None
    thoughts = []
    for part in content.parts:
        if part.text and part.thought:
            thoughts.append(part.text)
    return "\n".join(thoughts) if thoughts else None


async def _check_actionability(
    client: AsyncClient,
    output: SignalEmitterOutput,
    actionability_prompt: str,
) -> tuple[bool, str | None]:
    prompt = actionability_prompt.format(description=output.description)
    for attempt in range(LLM_MAX_ATTEMPTS):
        if attempt > 0:
            await asyncio.sleep(LLM_RETRY_INITIAL_DELAY_SECONDS * (LLM_RETRY_BACKOFF_COEFFICIENT ** (attempt - 1)))
        try:
            response = await asyncio.wait_for(
                client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=[prompt],
                    config=types.GenerateContentConfig(
                        max_output_tokens=LLM_THINKING_BUDGET_TOKENS + 128,
                        thinking_config=types.ThinkingConfig(
                            thinking_budget=LLM_THINKING_BUDGET_TOKENS,
                            include_thoughts=True,
                        ),
                    ),
                ),
                timeout=LLM_CALL_TIMEOUT_SECONDS,
            )
            thoughts = _extract_thoughts(response)
            response_text = (response.text or "").strip().upper()
            return "NOT_ACTION" not in response_text, thoughts
        except Exception as e:
            posthoganalytics.capture_exception(
                e,
                properties={
                    "ai_product": "signals",
                    "tag": "signals_import",
                    "error_type": "actionability_check_failed",
                    "source_type": output.source_type,
                    "source_id": output.source_id,
                    "attempt": attempt + 1,
                },
            )
    # Assume actionable if all retries exhausted
    return True, None


async def filter_actionable(
    outputs: list[SignalEmitterOutput],
    actionability_prompt: str,
    extra: dict[str, Any],
) -> list[SignalEmitterOutput]:
    client = genai.AsyncClient(api_key=settings.GEMINI_API_KEY)
    semaphore = asyncio.Semaphore(LLM_CONCURRENCY_LIMIT)
    _safe_heartbeat()
    checked_count = 0

    async def _bounded_check(output: SignalEmitterOutput) -> tuple[bool, str | None]:
        nonlocal checked_count
        async with semaphore:
            try:
                result = await _check_actionability(client, output, actionability_prompt)
            except Exception:
                logger.exception(
                    "Actionability check failed, assuming actionable",
                    signal_source_id=output.source_id,
                    **extra,
                )
                return True, None
            finally:
                checked_count += 1
                if checked_count % LLM_CONCURRENCY_LIMIT == 0:
                    _safe_heartbeat()
            return result

    tasks: dict[int, asyncio.Task[tuple[bool, str | None]]] = {}
    async with asyncio.TaskGroup() as tg:
        for i, output in enumerate(outputs):
            tasks[i] = tg.create_task(_bounded_check(output))
    actionable = []
    filtered_count = 0
    for i, output in enumerate(outputs):
        is_actionable, thoughts = tasks[i].result()
        if is_actionable:
            actionable.append(output)
        else:
            filtered_count += 1
            logger.info(
                "Filtered non-actionable signal",
                signal_source_type=output.source_type,
                signal_source_id=output.source_id,
                thoughts=thoughts,
                **extra,
            )
    if filtered_count > 0:
        logger.info(
            f"Filtered {filtered_count} non-actionable records out of {len(outputs)}",
            signals_type="data-import-signals",
            **extra,
        )
    return actionable


def _estimate_output_payload_bytes(output: SignalEmitterOutput) -> int:
    return len(
        json.dumps(
            {
                "source_type": output.source_type,
                "source_id": output.source_id,
                "description": output.description,
                "weight": output.weight,
                "extra": output.extra,
            },
        ).encode("utf-8")
    )


async def _emit_signals(
    team: Team,
    outputs: list[SignalEmitterOutput],
    extra: dict[str, Any],
) -> int:
    semaphore = asyncio.Semaphore(EMIT_CONCURRENCY_LIMIT)
    _safe_heartbeat()
    completed_count = 0

    async def _bounded_emit(output: SignalEmitterOutput) -> bool:
        nonlocal completed_count
        async with semaphore:
            try:
                payload_bytes = _estimate_output_payload_bytes(output)
                if payload_bytes > TEMPORAL_PAYLOAD_MAX_BYTES:
                    without_extra = dataclasses.replace(output, extra={})
                    if _estimate_output_payload_bytes(without_extra) > TEMPORAL_PAYLOAD_MAX_BYTES:
                        msg = "Signal payload exceeds Temporal limit even without extra metadata"
                        logger.error(
                            msg,
                            signal_source_type=output.source_type,
                            signal_source_id=output.source_id,
                            **extra,
                        )
                        raise ValueError(msg)
                    logger.error(
                        f"Signal extra metadata too large ({payload_bytes} bytes), emitting without extra",
                        signal_source_type=output.source_type,
                        signal_source_id=output.source_id,
                        **extra,
                    )
                    output = without_extra
                await emit_signal(
                    team=team,
                    source_product=output.source_product,
                    source_type=output.source_type,
                    source_id=output.source_id,
                    description=output.description,
                    weight=output.weight,
                    extra=output.extra,
                )
                return True
            except Exception as e:
                logger.exception(f"Error emitting signal for record: {e}", **extra)
                return False
            finally:
                completed_count += 1
                if completed_count % EMIT_CONCURRENCY_LIMIT == 0:
                    _safe_heartbeat()

    results: dict[int, asyncio.Task[bool]] = {}
    async with asyncio.TaskGroup() as tg:
        for i, output in enumerate(outputs):
            results[i] = tg.create_task(_bounded_emit(output))
    succeeded = sum(1 for task in results.values() if task.result())
    if succeeded == 0 and len(outputs) > 0:
        raise RuntimeError(f"All {len(outputs)} signal emissions failed")
    return succeeded


async def run_signal_pipeline(
    team: Team,
    config: SignalSourceTableConfig,
    records: list[dict[str, Any]],
    extra: dict[str, Any],
) -> dict[str, Any]:
    source_label = f"{config.source_product}/{config.source_type}"

    if not records:
        logger.warning(f"No new records found for {source_label}", **extra)
        return {"status": "success", "reason": "no_new_records", "signals_emitted": 0}

    outputs, error_count = build_emitter_outputs(
        team_id=team.id,
        records=records,
        emitter=config.emitter,
    )
    # Only fail if every record raised — emitters may return None as a benign skip,
    # so a mix of skips and errors should fall through to the no_actionable_records path.
    if error_count == len(records):
        raise ApplicationError(
            f"All {len(records)} records failed emitter for {source_label}",
            non_retryable=True,
        )
    logger.info(f"Built {len(outputs)} signal outputs from {len(records)} records for {source_label}", **extra)

    organization = await database_sync_to_async(lambda: team.organization)()
    for output in outputs:
        _capture_pipeline_stage("signal_data_source_entered", team, organization, output)

    if config.summarization_prompt is not None and config.description_summarization_threshold_chars is not None:
        threshold = config.description_summarization_threshold_chars
        pre_summary_by_id = {o.source_id: o for o in outputs}
        outputs = await summarize_long_descriptions(
            outputs=outputs,
            summarization_prompt=config.summarization_prompt,
            threshold=threshold,
            extra=extra,
        )
        for output in outputs:
            pre = pre_summary_by_id.get(output.source_id)
            if pre is not None and len(pre.description) > threshold:
                _capture_pipeline_stage("signal_data_source_summarized", team, organization, output)

    if config.actionability_prompt:
        pre_filter_by_id = {o.source_id: o for o in outputs}
        outputs = await filter_actionable(
            outputs=outputs,
            actionability_prompt=config.actionability_prompt,
            extra=extra,
        )
        post_filter_ids = {o.source_id for o in outputs}
        for source_id, output in pre_filter_by_id.items():
            if source_id not in post_filter_ids:
                _capture_pipeline_stage("signal_data_source_filtered", team, organization, output)

    if not outputs:
        logger.warning(f"No actionable records after filtering for {source_label}", **extra)
        return {"status": "success", "reason": "no_actionable_records", "signals_emitted": 0}

    signals_emitted = await _emit_signals(
        team=team,
        outputs=outputs,
        extra=extra,
    )
    logger.info(f"Emitted {signals_emitted} signals for {source_label}", **extra)
    return {"status": "success", "signals_emitted": signals_emitted}
