from collections.abc import Callable

from django.http import HttpRequest, HttpResponseBase

from rest_framework.request import Request

from posthog.exceptions_capture import capture_exception

_CALLBACKS_ATTR = "_posthog_after_response_callbacks"


def run_after_response(request: HttpRequest | Request | None, callback: Callable[[], None]) -> None:
    """
    Runs `callback` once the response has gone to the client, so the user does not wait for it.
    Outside a request that passed through `AfterResponseMiddleware`, it runs at once.
    """
    callbacks: list[Callable[[], None]] | None = getattr(request, _CALLBACKS_ATTR, None)
    if callbacks is None:
        callback()
    else:
        callbacks.append(callback)


class AfterResponseMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        callbacks: list[Callable[[], None]] = []
        setattr(request, _CALLBACKS_ATTR, callbacks)
        response = self.get_response(request)
        # Django calls these closers after it sends the last byte of the response, and before it
        # closes the request's database connections. The list is private, so the stubs leave it out.
        response._resource_closers.extend(  # type: ignore[attr-defined]
            _reporting_failures(callback) for callback in callbacks
        )
        return response


def _reporting_failures(callback: Callable[[], None]) -> Callable[[], None]:
    def run() -> None:
        try:
            callback()
        except Exception as e:
            capture_exception(e)

    return run
