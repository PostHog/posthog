"""
Celery tasks for the gateway credential cache.

Independent of the team_metadata / team-llm-gateway pipelines so the caches can
fail or roll back without affecting each other. The signal handlers that drive
these tasks live in
posthog/storage/gateway_credential_signal_handlers.py.
"""

import time

from django.conf import settings

import structlog
from celery import shared_task

from posthog.models.oauth import OAuthAccessToken
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.scoping_audit import skip_team_scope_audit
from posthog.storage.gateway_credential_cache import (
    GATEWAY_CREDENTIAL_REQUIRED_SCOPE,
    project_gateway_credential,
    refresh_all_gateway_credentials,
)
from posthog.storage.hypercache_manager import HYPERCACHE_SIGNAL_UPDATE_COUNTER
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

_NAMESPACE = "gateway_credential"
_SECRET_KEY_KIND = "project_secret_api_key"
_OAUTH_KIND = "oauth_access_token"


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def update_gateway_credential_cache_task(credential_kind: str, credential_id: str) -> None:
    if credential_kind == _SECRET_KEY_KIND:
        credential = ProjectSecretAPIKey.objects.select_related("gateway__team").filter(pk=credential_id).first()
    elif credential_kind == _OAUTH_KIND:
        credential = (
            OAuthAccessToken.objects.select_related("user", "application__gateway__team")
            .filter(pk=credential_id)
            .first()
        )
    else:
        logger.warning("Unknown credential kind for gateway credential update", kind=credential_kind)
        return

    if credential is None:
        # Deleted between enqueue and run; pre_delete already cleared the entry.
        logger.debug("Credential gone for gateway credential update", kind=credential_kind)
        return

    project_gateway_credential(credential)
    HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(namespace=_NAMESPACE, operation="update", result="success").inc()


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def reproject_user_gateway_credentials_task(user_id: int) -> None:
    """Re-project a user's OAuth credentials after a user/membership/RBAC change.
    Project secret keys have no user, so they're unaffected and not touched here."""
    for token in OAuthAccessToken.objects.select_related("user", "application__gateway__team").filter(
        scope__iregex=r"(^|\s)llm_gateway:read(\s|$)", user_id=user_id, application_id__isnull=False
    ):
        project_gateway_credential(token)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def reproject_gateway_bound_credentials_task(gateway_id: str) -> None:
    """Re-project every credential bound to a gateway after its slug changed."""
    for secret_key in ProjectSecretAPIKey.objects.select_related("gateway__team").filter(
        gateway_id=gateway_id, scopes__contains=[GATEWAY_CREDENTIAL_REQUIRED_SCOPE]
    ):
        project_gateway_credential(secret_key)
    for token in OAuthAccessToken.objects.select_related("user", "application__gateway__team").filter(
        application__gateway_id=gateway_id,
        scope__iregex=r"(^|\s)llm_gateway:read(\s|$)",
        application_id__isnull=False,
    ):
        project_gateway_credential(token)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def reproject_oauth_application_gateway_credentials_task(application_id: str) -> None:
    """Re-project an OAuth application's tokens after its gateway binding changed.
    The binding lives on the application, not the token, so a token save never fires."""
    for token in OAuthAccessToken.objects.select_related("user", "application__gateway__team").filter(
        application_id=application_id, scope__iregex=r"(^|\s)llm_gateway:read(\s|$)"
    ):
        project_gateway_credential(token)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def reproject_team_gateway_credentials_task(team_id: int) -> None:
    """Re-project the team's gateway credentials after an api_token rotation
    (project_token changes) or a project access-control change (OAuth RBAC)."""
    for secret_key in ProjectSecretAPIKey.objects.select_related("gateway__team").filter(
        gateway__team_id=team_id, scopes__contains=[GATEWAY_CREDENTIAL_REQUIRED_SCOPE]
    ):
        project_gateway_credential(secret_key)
    for token in OAuthAccessToken.objects.select_related("user", "application__gateway__team").filter(
        application__gateway__team_id=team_id,
        scope__iregex=r"(^|\s)llm_gateway:read(\s|$)",
        application_id__isnull=False,
    ):
        project_gateway_credential(token)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def refresh_gateway_credentials() -> None:
    """Hourly: re-project every credential granted llm_gateway:read so the cache
    stays warm. This only refreshes still-eligible credentials, so it heals missed
    *additions*, not removals — a revoked credential is cleared by its signal or,
    failing that, by blob TTL expiry."""
    if not settings.AI_GATEWAY_REDIS_URL:
        logger.info("AI gateway Redis URL not set, skipping gateway credential refresh")
        return

    start_time = time.time()
    try:
        projected = refresh_all_gateway_credentials()
        logger.info(
            "Completed gateway credential refresh",
            projected=projected,
            duration_seconds=time.time() - start_time,
        )
    except Exception as e:
        logger.exception(
            "Failed to complete gateway credential refresh",
            error=str(e),
            duration_seconds=time.time() - start_time,
        )
        raise
