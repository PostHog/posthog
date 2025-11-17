from datetime import datetime, timedelta
from typing import Optional

from django.conf import settings

import requests
import structlog

logger = structlog.get_logger(__name__)


_site_reachable: Optional[bool] = None
_site_reachable_exception: Optional[Exception] = None
_site_reachable_checked_at: Optional[datetime] = None


def is_site_url_reachable() -> bool:
    """
    Attempt to GET the SITE_ URL and log an error if it's not reachable
    or if the HTTP status code indicates an error
    """

    global _site_reachable
    global _site_reachable_checked_at
    global _site_reachable_exception

    if not settings.SITE_URL:
        return False

    if _site_reachable_checked_at and _site_reachable_checked_at > datetime.now() - timedelta(minutes=1):
        _site_reachable_checked_at = None

    if _site_reachable_checked_at is None:
        _site_reachable_checked_at = datetime.now()

        try:
            response = requests.get(settings.SITE_URL, timeout=5)
            _site_reachable = response.status_code < 400
            _site_reachable_exception = (
                None if _site_reachable else Exception(f"HTTP status code: {response.status_code}")
            )
        except Exception as e:
            _site_reachable_exception = e
            _site_reachable = False

    return _site_reachable or False


def log_error_if_site_url_not_reachable() -> None:
    if not settings.SITE_URL:
        logger.error("site_url_not_set")
    elif not is_site_url_reachable():
        logger.error(
            "site_url_not_reachable",
            site_url=settings.SITE_URL,
            exception=_site_reachable_exception,
        )
