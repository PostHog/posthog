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

    def capture_ph_event(*args: Any, **kwargs: Any) -> None:
        if is_cloud() and ph_client:
            ph_client.capture(*args, **kwargs)

    # Flush even when the caller's block raises — events already captured
    # before the exception shouldn't be dropped with the buffer.
    try:
        yield capture_ph_event
    finally:
        ph_client.shutdown()


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
