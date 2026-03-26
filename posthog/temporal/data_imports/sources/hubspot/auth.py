from django.conf import settings

import requests
import structlog

logger = structlog.get_logger(__name__)


def hubspot_refresh_access_token(refresh_token: str, source_id: str | None = None) -> str:
    res = requests.post(
        "https://api.hubapi.com/oauth/v1/token",
        data={
            "grant_type": "refresh_token",
            "client_id": settings.HUBSPOT_APP_CLIENT_ID,
            "client_secret": settings.HUBSPOT_APP_CLIENT_SECRET,
            "refresh_token": refresh_token,
        },
    )

    if res.status_code != 200:
        err_message = res.json()["message"]
        raise Exception(err_message)

    access_token = res.json()["access_token"]

    if source_id:
        _update_source_job_inputs(source_id, access_token)

    return access_token


def hubspot_access_token_is_valid(access_token: str) -> bool:
    res = requests.get(
        "https://api.hubapi.com/oauth/v1/access-tokens/" + access_token,
    )
    return res.status_code == 200


def _update_source_job_inputs(source_id: str, access_token: str) -> None:
    from products.data_warehouse.backend.models.external_data_source import ExternalDataSource

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
    res = requests.post(
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
