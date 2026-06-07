"""
Celery tasks for the first-party gateway policy cache.

Independent of the team_metadata / team-llm-gateway pipelines so the caches can
fail or roll back without affecting each other. The signal handlers that drive
these tasks live in
posthog/storage/first_party_gateway_policy_signal_handlers.py.
"""

import time

from django.conf import settings

import structlog
from celery import shared_task

from posthog.models.oauth import OAuthAccessToken
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.scoping_audit import skip_team_scope_audit
from posthog.storage.first_party_gateway_policy_cache import (
    FIRST_PARTY_REQUIRED_SCOPE,
    project_first_party_policy,
    refresh_all_first_party_policies,
)
from posthog.storage.hypercache_manager import HYPERCACHE_SIGNAL_UPDATE_COUNTER
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

_NAMESPACE = "first_party_gateway_policy"
_PAK_KIND = "personal_api_key"
_OAUTH_KIND = "oauth_access_token"


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def update_first_party_policy_cache_task(credential_kind: str, credential_id: str) -> None:
    if credential_kind == _PAK_KIND:
        credential = PersonalAPIKey.objects.select_related("user", "gateway__team").filter(pk=credential_id).first()
    elif credential_kind == _OAUTH_KIND:
        credential = (
            OAuthAccessToken.objects.select_related("user", "application__gateway__team")
            .filter(pk=credential_id)
            .first()
        )
    else:
        logger.warning("Unknown credential kind for first-party policy update", kind=credential_kind)
        return

    if credential is None:
        # Deleted between enqueue and run; pre_delete already cleared the entry.
        logger.debug("Credential gone for first-party policy update", kind=credential_kind)
        return

    project_first_party_policy(credential)
    HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(namespace=_NAMESPACE, operation="update", result="success").inc()


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def reproject_user_first_party_policies_task(user_id: int) -> None:
    """Re-project a user's gateway credentials after an is_active change (deactivation clears)."""
    for pak in PersonalAPIKey.objects.select_related("user", "gateway__team").filter(
        user_id=user_id, scopes__contains=[FIRST_PARTY_REQUIRED_SCOPE]
    ):
        project_first_party_policy(pak)
    for token in OAuthAccessToken.objects.select_related("user", "application__gateway__team").filter(
        scope__iregex=r"(^|\s)llm_gateway:read(\s|$)", user_id=user_id, application_id__isnull=False
    ):
        project_first_party_policy(token)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def reproject_gateway_first_party_policies_task(gateway_id: str) -> None:
    """Re-project every credential bound to a gateway after its slug changed."""
    for pak in PersonalAPIKey.objects.select_related("user", "gateway__team").filter(
        gateway_id=gateway_id, scopes__contains=[FIRST_PARTY_REQUIRED_SCOPE]
    ):
        project_first_party_policy(pak)
    for token in OAuthAccessToken.objects.select_related("user", "application__gateway__team").filter(
        application__gateway_id=gateway_id,
        scope__iregex=r"(^|\s)llm_gateway:read(\s|$)",
        application_id__isnull=False,
    ):
        project_first_party_policy(token)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def reproject_team_first_party_policies_task(team_id: int) -> None:
    """Re-project every credential bound to a gateway on this team after a project
    access-control change, since that flips the projection's RBAC check."""
    for pak in PersonalAPIKey.objects.select_related("user", "gateway__team").filter(
        gateway__team_id=team_id, scopes__contains=[FIRST_PARTY_REQUIRED_SCOPE]
    ):
        project_first_party_policy(pak)
    for token in OAuthAccessToken.objects.select_related("user", "application__gateway__team").filter(
        application__gateway__team_id=team_id,
        scope__iregex=r"(^|\s)llm_gateway:read(\s|$)",
        application_id__isnull=False,
    ):
        project_first_party_policy(token)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def refresh_first_party_gateway_policies() -> None:
    """Hourly: re-project every credential granted llm_gateway:read so the cache
    stays warm. This only refreshes still-eligible credentials, so it heals missed
    *additions*, not removals — a revoked credential is cleared by its signal or,
    failing that, by blob TTL expiry."""
    if not settings.AI_GATEWAY_REDIS_URL:
        logger.info("AI gateway Redis URL not set, skipping first-party policy refresh")
        return

    start_time = time.time()
    try:
        projected = refresh_all_first_party_policies()
        logger.info(
            "Completed first-party gateway policy refresh",
            projected=projected,
            duration_seconds=time.time() - start_time,
        )
    except Exception as e:
        logger.exception(
            "Failed to complete first-party gateway policy refresh",
            error=str(e),
            duration_seconds=time.time() - start_time,
        )
        raise
