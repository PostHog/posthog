from django.conf import settings
from django.urls import URLPattern, URLResolver

import structlog

logger = structlog.get_logger(__name__)

ee_urlpatterns: list[URLPattern | URLResolver] = []
try:
    from ee import urls
except ImportError:
    if settings.DEBUG:
        logger.warning("Could not import ee.urls", exc_info=True)
else:
    ee_urlpatterns = urls.urlpatterns
    urls.extend_api_router()
