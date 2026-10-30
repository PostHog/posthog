import contextvars

import pytest
from unittest import mock

from django.core.handlers.asgi import ASGIHandler
from django.http import HttpRequest, HttpResponse

from posthog.asgi import PostHogASGIHandler

_set_during_request: contextvars.ContextVar[str | None] = contextvars.ContextVar("set_during_request", default=None)


async def _fake_get_response(self: ASGIHandler, request: HttpRequest) -> HttpResponse:
    _set_during_request.set("leaked")
    return HttpResponse("ok")


@pytest.mark.asyncio
async def test_request_context_changes_do_not_reach_the_handler_task() -> None:
    handler = PostHogASGIHandler.__new__(PostHogASGIHandler)

    with mock.patch.object(ASGIHandler, "run_get_response", _fake_get_response):
        response = await handler.run_get_response(HttpRequest())

    assert response.status_code == 200
    assert _set_during_request.get() is None
