from collections.abc import Mapping
from contextlib import contextmanager
from numbers import Number
from typing import Any
from uuid import UUID

import structlog
import posthoganalytics

from posthog.cloud_utils import is_cloud
from posthog.utils import get_instance_region

PH_US_API_KEY = "sTMFPsFhdP1Ssg"
PH_US_HOST = "https://us.i.posthog.com"

PH_EU_API_KEY = "phc_dZ4GK1LRjhB97XozMSkEwPXx7OVANaJEwLErkY1phUF"
PH_EU_HOST = "https://eu.i.posthog.com"

logger = structlog.get_logger(__name__)


def feature_enabled_or_false(
    key: str,
    distinct_id: Number | str | UUID | int,
    groups: Mapping[str, str | int] | None = None,
    person_properties: dict[str, Any] | None = None,
    group_properties: dict[str, dict[str, Any]] | None = None,
    only_evaluate_locally: bool = False,
    send_feature_flag_events: bool = True,
    disable_geoip: bool | None = None,
    device_id: str | None = None,
) -> bool:
    return (
        posthoganalytics.feature_enabled(
            key,
            distinct_id,
            groups=groups,
            person_properties=person_properties,
            group_properties=group_properties,
            only_evaluate_locally=only_evaluate_locally,
            send_feature_flag_events=send_feature_flag_events,
            disable_geoip=disable_geoip,
            device_id=device_id,
        )
        is True
    )


def get_regional_ph_client(**kwargs: Any):
    if not is_cloud():
        return

    # send EU data to EU, US data to US
    region = get_instance_region()

    if not region:
        return

    return get_client(region, **kwargs)


class ScopedCapture:
    """The callable `ph_scoped_capture` yields: enqueues events, and exposes `flush()`.

    `__call__` only enqueues into the client's buffer; delivery happens on the background
    consumer and at context exit. Callers that checkpoint durable "events delivered" state
    (e.g. an idempotency stamp) must call `flush()` first, so that a crash after the
    checkpoint can't lose events still sitting in the buffer.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        if is_cloud() and self._client:
            self._client.capture(*args, **kwargs)

    def flush(self) -> None:
        """Wait for every queued event to be attempted. Blocks; keep it off an event loop.

        `timeout_seconds=None` on purpose — the SDK's default is a 10 second budget, and on expiry
        it logs and returns with items still queued, giving a caller no way to tell a drained buffer
        from an abandoned one. A checkpoint written on that return is exactly the loss the flush is
        there to prevent. Unbounded turns that into a caller-visible stall instead, which is the
        better failure: nothing is checkpointed, so the work is simply retried.

        It is "attempted", not "delivered": the SDK's consumer acknowledges a batch on its way out
        whether or not the request succeeded, so a batch that exhausts its retries is dropped with
        only a log line. Delivery past that point is not something this call can promise.
        """
        if self._client:
            self._client.flush(timeout_seconds=None)


@contextmanager
def ph_scoped_capture():
    """Use this instead of posthoganalytics.capture() in Celery tasks — the global
    client's background flush may never run before the worker exits, silently losing events.
    This creates a dedicated client and flushes on context-manager exit.

    Usage::

        with ph_scoped_capture() as capture:
            capture(distinct_id="...", event="my_event", properties={...})
    """
    ph_client = get_client()

    # Flush even when the caller's block raises — events already captured
    # before the exception shouldn't be dropped with the buffer.
    try:
        yield ScopedCapture(ph_client)
    finally:
        ph_client.shutdown()


def get_client(region: str = "US", **kwargs: Any):
    from posthoganalytics import Posthog

    api_key = None
    host = None
    if region == "EU":
        api_key = PH_EU_API_KEY
        host = PH_EU_HOST
    elif region == "US":
        api_key = PH_US_API_KEY
        host = PH_US_HOST
    else:
        return

    return Posthog(
        api_key,
        host=host,
        super_properties={"region": region},
        _use_ai_lane=True,
        _enable_multimodal_capture=True,
        **kwargs,
    )
