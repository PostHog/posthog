import threading
from collections.abc import Mapping
from contextlib import contextmanager
from numbers import Number
from typing import Any
from uuid import UUID

from django.conf import settings

import structlog
import posthoganalytics

from posthog.cloud_utils import is_cloud
from posthog.settings.ingestion import DedicatedAIEndpointRollout
from posthog.utils import get_instance_region

PH_US_API_KEY = "sTMFPsFhdP1Ssg"
PH_US_HOST = "https://us.i.posthog.com"

PH_EU_API_KEY = "phc_dZ4GK1LRjhB97XozMSkEwPXx7OVANaJEwLErkY1phUF"
PH_EU_HOST = "https://eu.i.posthog.com"

logger = structlog.get_logger(__name__)

_DEDICATED_AI_ENDPOINT_STAGES = (DedicatedAIEndpointRollout.RUNNER, DedicatedAIEndpointRollout.ALL)


def _use_dedicated_ai_endpoint(caller_stage: DedicatedAIEndpointRollout) -> bool:
    rollout = settings.POSTHOG_DEDICATED_AI_ENDPOINT_ROLLOUT
    if rollout is DedicatedAIEndpointRollout.OFF:
        return False
    return _DEDICATED_AI_ENDPOINT_STAGES.index(rollout) >= _DEDICATED_AI_ENDPOINT_STAGES.index(caller_stage)


def enable_dedicated_ai_endpoint_for_default_client() -> None:
    """Route the module-level default client's `$ai_*` events to the dedicated AI
    endpoint at the `all` rollout stage.

    Deliberate workaround: the SDK's lazy `setup()` doesn't accept
    `_dedicated_ai_endpoint`, and we want to finish testing the endpoint on our own
    traffic before rethinking the flag as a public option threaded through the
    SDK's normal construction paths. Mutating the constructed client is safe: it
    and its consumers read the flag per batch, and the SDK's post-fork consumer
    rebuild copies it from the old consumers.
    """
    if not _use_dedicated_ai_endpoint(DedicatedAIEndpointRollout.ALL):
        return
    client = posthoganalytics.default_client
    if client is None:
        return
    client._dedicated_ai_endpoint = True
    for consumer in client.consumers or []:
        consumer.dedicated_ai_endpoint = True


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


PH_SCOPED_CAPTURE_FLUSH_TIMEOUT_SECONDS = 10.0


@contextmanager
def ph_scoped_capture():
    """Capture PostHog telemetry with a dedicated client that flushes on context exit.

    Prefer plain ``posthoganalytics.capture()`` — it is a non-blocking enqueue and is safe
    in Celery tasks too, since ``on_worker_process_shutdown`` flushes the global client's
    queue (bounded) when a prefork child recycles or exits. Reach for this scoped variant
    in short-lived processes without such a lifecycle hook (management commands,
    dagster/temporal one-shots) or when the events must be flushed before moving on.

    Exit is bounded: the shutdown runs on a daemon thread joined for
    ``PH_SCOPED_CAPTURE_FLUSH_TIMEOUT_SECONDS`` and is abandoned on timeout (it keeps
    draining in the background while the process lives) — a degraded ingestion endpoint
    must not hang request threads or worker slots.

    Usage::

        with ph_scoped_capture() as capture:
            capture(distinct_id="...", event="my_event", properties={...})
    """
    # A fresh client's consumer holds its first batch for the default 5s flush_interval,
    # which would stall every healthy exit by ~5s — flush almost immediately instead.
    ph_client = get_client(flush_interval=0.3)

    def capture_ph_event(*args: Any, **kwargs: Any) -> None:
        if is_cloud() and ph_client:
            ph_client.capture(*args, **kwargs)

    # Flush even when the caller's block raises — events already captured
    # before the exception shouldn't be dropped with the buffer.
    try:
        yield capture_ph_event
    finally:

        def _shutdown() -> None:
            try:
                ph_client.shutdown()
            except Exception:
                logger.warning("ph_scoped_capture_shutdown_failed", exc_info=True)

        shutdown_thread = threading.Thread(target=_shutdown, name="ph-scoped-capture-shutdown", daemon=True)
        shutdown_thread.start()
        shutdown_thread.join(timeout=PH_SCOPED_CAPTURE_FLUSH_TIMEOUT_SECONDS)
        if shutdown_thread.is_alive():
            logger.warning("ph_scoped_capture_shutdown_timed_out")


def get_client(
    region: str = "US",
    *,
    dedicated_ai_endpoint_stage: DedicatedAIEndpointRollout = DedicatedAIEndpointRollout.ALL,
    **kwargs: Any,
):
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
        _dedicated_ai_endpoint=_use_dedicated_ai_endpoint(dedicated_ai_endpoint_stage),
        **kwargs,
    )
