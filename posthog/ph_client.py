import os
import atexit
import threading
from collections.abc import Mapping
from contextlib import contextmanager
from numbers import Number
from typing import Any, cast
from uuid import UUID

from django.conf import settings

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


def get_feature_flag_or_none(
    key: str,
    distinct_id: str,
    groups: dict[str, str] | None = None,
    group_properties: dict[str, dict[str, Any]] | None = None,
    only_evaluate_locally: bool = False,
    send_feature_flag_events: bool = True,
) -> str | bool | None:
    """Variant-returning sibling of feature_enabled_or_false that never raises, so callers on
    paths that must not fail (cache writes, background tasks) can treat any failure as flag-off."""
    try:
        # The library annotates the return as Optional[FeatureFlag], but at runtime a plain
        # variant string or bool comes back, so cast like ee/hogai/utils/feature_flags.py does.
        return cast(
            "str | bool | None",
            posthoganalytics.get_feature_flag(
                key,
                distinct_id,
                groups=groups,
                group_properties=group_properties,
                only_evaluate_locally=only_evaluate_locally,
                send_feature_flag_events=send_feature_flag_events,
            ),
        )
    except Exception:
        logger.warning("get_feature_flag_failed", flag_key=key, exc_info=True)
        return None


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
def ph_scoped_capture(region: str = "US"):
    """Use this instead of posthoganalytics.capture() in Celery tasks — the global
    client's background flush may never run before the worker exits, silently losing events.
    This creates a dedicated client and flushes on context-manager exit.
    Pass the deployment region when events must stay in their regional project.

    In a long-lived worker (e.g. Temporal activities), prefer `ph_background_capture` —
    the client setup and synchronous flush here add seconds of blocking per call.

    Usage::

        with ph_scoped_capture() as capture:
            capture(distinct_id="...", event="my_event", properties={...})
    """
    ph_client = get_client(region)

    # Flush even when the caller's block raises — events already captured
    # before the exception shouldn't be dropped with the buffer.
    try:
        yield ScopedCapture(ph_client)
    finally:
        ph_client.shutdown()


_background_client: Any = None
_background_client_lock = threading.Lock()


def ph_background_capture() -> ScopedCapture:
    """Capture through a process-lifetime client whose batches the SDK's consumer
    thread delivers in the background — no per-call client setup or blocking flush.

    For long-lived processes (e.g. Temporal workers) where `ph_scoped_capture`'s
    per-call dedicated client and synchronous flush would sit on the hot path.
    Delivery is best-effort: a bounded flush runs at interpreter exit, so don't use
    this where delivery must be confirmed before checkpointing durable state.
    """
    global _background_client
    if _background_client is None:
        with _background_client_lock:
            if _background_client is None:
                _background_client = get_client()
                # The SDK's own atexit hook only joins the consumer mid-batch without
                # draining the queue. atexit is LIFO, so this flush (registered after
                # the client's hook) runs first and drains what a graceful shutdown
                # enqueued last. Bounded (SDK default 10s) so a dead network can't
                # stall process exit.
                atexit.register(_background_client.flush)
    return ScopedCapture(_background_client)


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

    # A fresh client does not inherit the module-level `disabled` flag that apps.py sets
    # under TEST, so without this a test that runs in cloud mode captures to the real
    # project. Callers can still pass `disabled` explicitly to override.
    kwargs.setdefault("disabled", bool(settings.TEST or os.environ.get("OPT_OUT_CAPTURE", False)))

    return Posthog(
        api_key,
        host=host,
        super_properties={"region": region},
        _use_ai_lane=True,
        _enable_multimodal_capture=True,
        **kwargs,
    )
