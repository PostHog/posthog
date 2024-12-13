from posthog.utils import get_instance_region
from posthog.cloud_utils import is_cloud
from typing import Any
import structlog

from contextlib import contextmanager

PH_US_API_KEY = "sTMFPsFhdP1Ssg"
PH_US_HOST = "https://us.i.posthog.com"

logger = structlog.get_logger(__name__)


def get_ph_client():
    from posthoganalytics import Posthog

    if not is_cloud():
        return

    # send EU data to EU, US data to US
    api_key = None
    host = None
    region = get_instance_region()
    if region == "EU":
        api_key = "phc_dZ4GK1LRjhB97XozMSkEwPXx7OVANaJEwLErkY1phUF"
        host = "https://eu.i.posthog.com"
    elif region == "US":
        api_key = PH_US_API_KEY
        host = PH_US_HOST

    if not api_key:
        return

    ph_client = Posthog(api_key, host=host)

    return ph_client


@contextmanager
def ph_us_client():
    from posthoganalytics import Posthog

    ph_client = Posthog(PH_US_API_KEY, host=PH_US_HOST)

    def capture_ph_event(*args: Any, **kwargs: Any) -> None:
        if is_cloud():
            properties = kwargs.get("properties", {})
            properties["region"] = get_instance_region()
            kwargs["properties"] = properties

            ph_client.capture(*args, **kwargs)
        else:
            logger.info("Captured event in US region", args, kwargs)

    yield capture_ph_event

    ph_client.shutdown()
