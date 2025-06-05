from posthog.utils import get_instance_region
from posthog.cloud_utils import is_cloud
from typing import Any
import structlog

from contextlib import contextmanager

PH_US_API_KEY = "sTMFPsFhdP1Ssg"
PH_US_HOST = "https://us.i.posthog.com"

PH_EU_API_KEY = "phc_dZ4GK1LRjhB97XozMSkEwPXx7OVANaJEwLErkY1phUF"
PH_EU_HOST = "https://eu.i.posthog.com"

logger = structlog.get_logger(__name__)


def get_regional_ph_client():
    if not is_cloud():
        return

    # send EU data to EU, US data to US
    region = get_instance_region()

    if not region:
        return

    return get_client(region)


@contextmanager
def ph_scoped_capture():
    ph_client = get_client()

    def capture_ph_event(*args: Any, **kwargs: Any) -> None:
        if is_cloud() and ph_client:
            ph_client.capture(*args, **kwargs)

    yield capture_ph_event

    ph_client.shutdown()


def get_client(region: str = "US"):
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

    return Posthog(api_key, host=host, super_properties={"region": region})
