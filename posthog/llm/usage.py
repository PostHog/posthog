from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from asgiref.sync import sync_to_async

if TYPE_CHECKING:
    import httpx

_usage_recorder: ContextVar[Callable[[str | None], None] | None] = ContextVar("llm_usage_recorder", default=None)


@contextmanager
def record_gateway_usage(recorder: Callable[[str | None], None]) -> Iterator[None]:
    token = _usage_recorder.set(recorder)
    try:
        yield
    finally:
        _usage_recorder.reset(token)


def _is_generation(response: httpx.Response) -> bool:
    return (
        response.is_success
        and response.request.method == "POST"
        and response.request.url.path.endswith(
            ("/v1/messages", "/v1/chat/completions", "/v1/responses", "/v1/systemone")
        )
    )


def record_gateway_response(response: httpx.Response) -> None:
    if (recorder := _usage_recorder.get()) is not None and _is_generation(response):
        recorder(response.headers.get("x-request-id"))


async def record_async_gateway_response(response: httpx.Response) -> None:
    if _usage_recorder.get() is not None:
        await sync_to_async(record_gateway_response)(response)


def record_unpriced_response(response: httpx.Response) -> None:
    if (recorder := _usage_recorder.get()) is not None and _is_generation(response):
        recorder(None)


async def record_async_unpriced_response(response: httpx.Response) -> None:
    if _usage_recorder.get() is not None:
        await sync_to_async(record_unpriced_response)(response)
