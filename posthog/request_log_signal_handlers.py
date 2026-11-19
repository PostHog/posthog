import time
from typing import Any
from urllib.parse import unquote_plus

from django.dispatch import receiver
from django.http import HttpRequest

from django_structlog import signals

_STARTED_AT_ATTR = "_structlog_started_at"

_CREDENTIAL_QUERY_PARAMS = frozenset({"personal_api_key", "token", "access_token", "api_key"})
_REDACTED = "<redacted>"


def redact_credential_query_params(request_line: str) -> str:
    path, separator, query = request_line.partition("?")
    if not separator:
        return request_line
    params = query.split("&")
    for index, param in enumerate(params):
        name, has_value, _ = param.partition("=")
        if has_value and unquote_plus(name).lower() in _CREDENTIAL_QUERY_PARAMS:
            params[index] = f"{name}={_REDACTED}"
    return f"{path}?{'&'.join(params)}"


@receiver(signals.bind_extra_request_metadata)
def record_request_start(request: HttpRequest, **kwargs: Any) -> None:
    setattr(request, _STARTED_AT_ATTR, time.monotonic())


@receiver(signals.bind_extra_request_metadata)
@receiver(signals.bind_extra_request_finished_metadata)
@receiver(signals.bind_extra_request_failed_metadata)
def redact_request_credentials(log_kwargs: dict[str, Any], **kwargs: Any) -> None:
    request_line = log_kwargs.get("request")
    if isinstance(request_line, str):
        log_kwargs["request"] = redact_credential_query_params(request_line)


@receiver(signals.bind_extra_request_finished_metadata)
@receiver(signals.bind_extra_request_failed_metadata)
def add_request_duration(request: HttpRequest, log_kwargs: dict[str, Any], **kwargs: Any) -> None:
    # Measured from django-structlog's RequestMiddleware, so middlewares above it in MIDDLEWARE are not counted.
    # For a streaming response this is the time to the response headers, not to the end of the stream.
    started_at = getattr(request, _STARTED_AT_ATTR, None)
    if started_at is not None:
        log_kwargs["duration_ms"] = round((time.monotonic() - started_at) * 1000, 1)
