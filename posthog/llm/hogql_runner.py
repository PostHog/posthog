from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from django.conf import settings

from asgiref.sync import async_to_sync

from posthog.hogql.errors import QueryError
from posthog.hogql.timings import HogQLTimings
from posthog.llm.gateway_client import get_async_llm_client

if TYPE_CHECKING:
    from posthog.hogql.transforms.llm_completions import LlmCompletionSpec
    from posthog.models import User


logger = logging.getLogger(__name__)


def apply_llm_completions(
    results: list[tuple] | list[list],
    specs: list["LlmCompletionSpec"],
    *,
    user: "User | None",
    timings: HogQLTimings,
) -> list[list]:
    """Replace rendered-prompt column values with LLM completions.

    Enforces a row cap before firing any calls; dedupes prompts within the query; caps
    concurrency and per-call timeout; per-row errors become ``None`` and are logged
    rather than failing the whole query.

    Returns a new results list (tuples converted to lists so cells can be mutated).
    """
    if not specs:
        return list(results)

    max_rows: int = getattr(settings, "HOGQL_LLM_COMPLETE_MAX_ROWS", 1000)
    if len(results) > max_rows:
        raise QueryError(
            f"__preview_llm_complete(): query would fire {len(results)} LLM calls, "
            f"which exceeds the limit of {max_rows}. Add a stricter LIMIT."
        )

    with timings.measure("llm_completions"):
        unique_calls = _collect_unique_calls(results, specs)
        if not unique_calls:
            return [list(row) for row in results]

        distinct_id = user.distinct_id if user is not None and getattr(user, "distinct_id", None) else None
        completions = async_to_sync(_fire_completions)(unique_calls, distinct_id=distinct_id)

        mutable_rows: list[list] = [list(row) for row in results]
        for spec in specs:
            for row in mutable_rows:
                prompt = row[spec.column_index]
                if not isinstance(prompt, str):
                    row[spec.column_index] = None
                    continue
                key = (spec.model, spec.system_prompt, prompt)
                row[spec.column_index] = completions.get(key)
        return mutable_rows


_CallKey = tuple[str, str | None, str]


def _collect_unique_calls(
    results: list[tuple] | list[list],
    specs: list["LlmCompletionSpec"],
) -> list[_CallKey]:
    seen: dict[_CallKey, None] = {}
    for row in results:
        for spec in specs:
            prompt = row[spec.column_index]
            if not isinstance(prompt, str):
                continue
            key: _CallKey = (spec.model, spec.system_prompt, prompt)
            if key not in seen:
                seen[key] = None
    return list(seen.keys())


async def _fire_completions(
    calls: list[_CallKey],
    *,
    distinct_id: str | None,
) -> dict[_CallKey, str | None]:
    concurrency: int = getattr(settings, "HOGQL_LLM_COMPLETE_CONCURRENCY", 20)
    timeout_seconds: float = getattr(settings, "HOGQL_LLM_COMPLETE_TIMEOUT_SECONDS", 30.0)
    max_tokens: int = getattr(settings, "HOGQL_LLM_COMPLETE_MAX_TOKENS", 512)

    client = get_async_llm_client("hogql")
    semaphore = asyncio.Semaphore(concurrency)

    async def one(key: _CallKey) -> str | None:
        model, system, prompt = key
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with semaphore:
            try:
                kwargs: dict = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                }
                if distinct_id:
                    kwargs["user"] = distinct_id
                response = await asyncio.wait_for(
                    client.chat.completions.create(**kwargs),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                logger.warning("llm_complete timeout", extra={"model": model})
                return None
            except Exception as exc:
                logger.warning("llm_complete error: %s", type(exc).__name__, extra={"model": model})
                return None
        try:
            return response.choices[0].message.content
        except (AttributeError, IndexError):
            logger.warning("llm_complete unexpected response shape", extra={"model": model})
            return None

    tasks = [asyncio.create_task(one(key)) for key in calls]
    values = await asyncio.gather(*tasks)
    return dict(zip(calls, values))
