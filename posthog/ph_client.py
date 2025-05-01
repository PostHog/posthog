import structlog
from django.conf import settings
from typing import Any
from contextlib import contextmanager

from posthog.cloud_utils import is_cloud
from posthoganalytics.exception_capture import Integrations
from posthog.utils import get_instance_region

PH_US_API_KEY = "sTMFPsFhdP1Ssg"
PH_US_HOST = "https://us.i.posthog.com"

logger = structlog.get_logger(__name__)


def get_us_client(**kwargs: Any):
    from posthoganalytics import Posthog

    if not is_cloud():
        return

    return Posthog(
        api_key=PH_US_API_KEY,
        host=PH_US_HOST,
        exception_autocapture_integrations=[Integrations.Django],
        enable_exception_autocapture=True,
        log_captured_exceptions=True,
        super_properties={"region": get_instance_region(), "celery": True, "instance": settings.SITE_URL},
        **kwargs,
    )


@contextmanager
def ph_scoped_capture():
    ph_client = get_us_client()

    def capture_ph_event(*args: Any, **kwargs: Any) -> None:
        if ph_client:
            ph_client.capture(*args, **kwargs)
        else:
            logger.info("Captured event in US region", args, kwargs)

    yield capture_ph_event

    ph_client.shutdown()
