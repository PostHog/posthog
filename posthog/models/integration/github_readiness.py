from __future__ import annotations

from dataclasses import field
from typing import TYPE_CHECKING

from django.db import models

from requests import RequestException
from rest_framework.exceptions import APIException

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.models.github_integration_base import GITHUB_REPOSITORY_CACHE_TTL_SECONDS, GitHubIntegrationError
from posthog.models.integration.refresh_tracking import refresh_backoff_active

if TYPE_CHECKING:
    from posthog.models.github_integration_base import GitHubIntegrationBase


class GitHubReadinessStatus(models.TextChoices):
    READY = "ready", "Connected"
    NOT_CONNECTED = "not_connected", "Connect GitHub"
    RECONNECT_REQUIRED = "reconnect_required", "Reconnect GitHub"
    NO_REPOSITORIES = "no_repositories", "Allow repository access"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable", "Checking GitHub access"


class GitHubAccessUnavailable(APIException):
    status_code = 409
    default_code = "github_access_unavailable"

    def __init__(self, status: GitHubReadinessStatus) -> None:
        messages = {
            GitHubReadinessStatus.NOT_CONNECTED: "Connect GitHub to start Self-Driving work.",
            GitHubReadinessStatus.RECONNECT_REQUIRED: "Reconnect GitHub to resume Self-Driving work.",
            GitHubReadinessStatus.NO_REPOSITORIES: "Allow access to at least one GitHub repository to resume Self-Driving work.",
            GitHubReadinessStatus.TEMPORARILY_UNAVAILABLE: "GitHub access is temporarily unavailable. Try again shortly.",
        }
        super().__init__(detail=messages[status], code=status.value)


@frozen
class GitHubReadiness:
    status: GitHubReadinessStatus
    retry_after: int = 0
    integration: GitHubIntegrationBase | None = field(default=None, repr=False)


def github_readiness(
    github: GitHubIntegrationBase, *, verify: bool = False, refresh_cache: bool = True
) -> GitHubReadiness:
    integration = github.integration
    if github.installation_unavailable():
        return GitHubReadiness(status=GitHubReadinessStatus.RECONNECT_REQUIRED, integration=github)
    try:
        if verify:
            if getattr(integration, "errors", "") == "TOKEN_REFRESH_FAILED":
                if refresh_backoff_active(integration):
                    return GitHubReadiness(status=GitHubReadinessStatus.TEMPORARILY_UNAVAILABLE, integration=github)
                github.refresh_access_token()
            if refresh_cache:
                has_repositories = bool(
                    github.sync_repository_cache(min_refresh_interval_seconds=GITHUB_REPOSITORY_CACHE_TTL_SECONDS)
                )
            else:
                repositories, _ = github.list_repositories(per_page=1)
                has_repositories = bool(repositories)
        else:
            if getattr(integration, "errors", "") == "TOKEN_REFRESH_FAILED":
                return GitHubReadiness(status=GitHubReadinessStatus.TEMPORARILY_UNAVAILABLE, integration=github)
            cached_nonempty = getattr(integration, "_github_has_repositories", None)
            has_repositories = bool(integration.repository_cache) if cached_nonempty is None else bool(cached_nonempty)
            if not has_repositories and github.repository_cache_is_stale():
                return GitHubReadiness(status=GitHubReadinessStatus.TEMPORARILY_UNAVAILABLE, integration=github)
    except (GitHubIntegrationError, GitHubRateLimitError, EgressBudgetExhausted, RequestException) as error:
        status = (
            GitHubReadinessStatus.RECONNECT_REQUIRED
            if github.installation_unavailable()
            else GitHubReadinessStatus.TEMPORARILY_UNAVAILABLE
        )
        return GitHubReadiness(
            status=status,
            integration=github,
            retry_after=(error.retry_after or 0) if isinstance(error, GitHubRateLimitError) else 0,
        )
    return GitHubReadiness(
        status=GitHubReadinessStatus.READY if has_repositories else GitHubReadinessStatus.NO_REPOSITORIES,
        integration=github,
    )
