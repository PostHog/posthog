import time
from typing import Any

from django.dispatch import receiver
from django.http import HttpRequest

from django_structlog import signals

_STARTED_AT_ATTR = "_structlog_started_at"


@receiver(signals.bind_extra_request_metadata)
def record_request_start(request: HttpRequest, **kwargs: Any) -> None:
    setattr(request, _STARTED_AT_ATTR, time.monotonic())


@receiver(signals.bind_extra_request_finished_metadata)
@receiver(signals.bind_extra_request_failed_metadata)
def add_request_duration(request: HttpRequest, log_kwargs: dict[str, Any], **kwargs: Any) -> None:
    # Measured from django-structlog's RequestMiddleware, so middlewares above it in MIDDLEWARE are not counted.
    # For a streaming response this is the time to the response headers, not to the end of the stream.
    started_at = getattr(request, _STARTED_AT_ATTR, None)
    if started_at is not None:
        log_kwargs["duration_ms"] = round((time.monotonic() - started_at) * 1000, 1)
