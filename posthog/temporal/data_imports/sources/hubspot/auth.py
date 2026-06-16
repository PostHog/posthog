from django.conf import settings

import requests
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.sources.common.http import make_tracked_session

logger = structlog.get_logger(__name__)


class HubspotRetryableError(Exception):
    """Transient HubSpot API failure (429 rate limit or 5xx) that should be retried with backoff."""

    pass


def _error_message_from_response(res: requests.Response) -> str:
    """Best-effort extraction of HubSpot's error message, tolerant of non-JSON or message-less bodies."""
    try:
        return res.json()["message"]
    except Exception:
        return res.text


@retry(
    retry=retry_if_exception_type((HubspotRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def hubspot_refresh_access_token(refresh_token: str, source_id: str | None = None) -> str:
    res = make_tracked_session().post(
        "https://api.hubapi.com/oauth/v1/token",
        data={
            "grant_type": "refresh_token",
            "client_id": settings.HUBSPOT_APP_CLIENT_ID,
            "client_secret": settings.HUBSPOT_APP_CLIENT_SECRET,
            "refresh_token": refresh_token,
        },
        timeout=60,
    )

    if res.status_code != 200:
        err_message = _error_message_from_response(res)
        # HubSpot rate-limits the OAuth token endpoint too (429 "You have reached your rate limit."),
        # and 5xx is transient. Back off and retry rather than crashing the sync. The @retry above
        # retries this call site (e.g. source.py's setup path, which has no surrounding retry loop);
        # callers in hubspot.py also treat HubspotRetryableError as retryable.
        if res.status_code == 429 or res.status_code >= 500:
            raise HubspotRetryableError(err_message)
        raise Exception(err_message)

    access_token = res.json()["access_token"]

    if source_id:
        _update_source_job_inputs(source_id, access_token)

    return access_token


def hubspot_access_token_is_valid(access_token: str) -> bool:
    res = make_tracked_session().get(
        "https://api.hubapi.com/oauth/v1/access-tokens/" + access_token,
    )
    return res.status_code == 200


def _update_source_job_inputs(source_id: str, access_token: str) -> None:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

    try:
        source = ExternalDataSource.objects.get(id=source_id)
        job_inputs = source.job_inputs or {}

        # Only persist for legacy sources that store credentials directly in job_inputs
        if "hubspot_integration_id" in job_inputs:
            return

        job_inputs["hubspot_secret_key"] = access_token
        source.job_inputs = job_inputs
        source.save(update_fields=["job_inputs"])
    except Exception:
        logger.exception("Failed to update job_inputs after HubSpot token refresh", source_id=source_id)


def get_hubspot_access_token_from_code(code: str, redirect_uri: str) -> tuple[str, str]:
    res = make_tracked_session().post(
        "https://api.hubapi.com/oauth/v1/token",
        data={
            "grant_type": "authorization_code",
            "client_id": settings.HUBSPOT_APP_CLIENT_ID,
            "client_secret": settings.HUBSPOT_APP_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )

    if res.status_code != 200:
        err_message = res.json()["message"]
        raise Exception(err_message)

    payload = res.json()

    return payload["access_token"], payload["refresh_token"]
