from collections.abc import Sequence
from enum import StrEnum

from django.conf import settings

import requests
import structlog

from posthog.egress.cloudflare import CloudflareEgressBudgetExhausted, CloudflarePurgeFailed, purge_urls
from posthog.exceptions_capture import capture_exception
from posthog.models import UploadedMedia

logger = structlog.get_logger(__name__)


class CdnPurgeResult(StrEnum):
    NOT_CONFIGURED = "not_configured"
    PURGED = "purged"
    FAILED = "failed"


def purge_media_from_cdn(media: Sequence[UploadedMedia]) -> CdnPurgeResult:
    """Ask the CDN in front of UPLOADED_MEDIA_PUBLIC_URL to drop its cached copies of these images.

    The success response is cached for years, so without a purge the CDN keeps serving an image
    after the origin stops.
    """
    zone_id = settings.UPLOADED_MEDIA_CDN_PURGE_ZONE_ID
    api_token = settings.UPLOADED_MEDIA_CDN_PURGE_TOKEN
    if not (settings.UPLOADED_MEDIA_PUBLIC_URL and zone_id and api_token):
        return CdnPurgeResult.NOT_CONFIGURED
    if not media:
        return CdnPurgeResult.PURGED
    try:
        purge_urls(
            [item.get_absolute_url() for item in media],
            zone_id=zone_id,
            api_token=api_token,
            source="uploaded_media_takedown",
        )
    except (CloudflarePurgeFailed, CloudflareEgressBudgetExhausted, requests.RequestException) as error:
        capture_exception(error)
        logger.warning("uploaded_media.cdn_purge_failed", media_ids=[str(item.id) for item in media], exc_info=True)
        return CdnPurgeResult.FAILED
    return CdnPurgeResult.PURGED
