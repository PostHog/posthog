"""Team-level GitHub integration primitives.

These wrap the three IO-heavy operations the ``IntegrationViewSet`` triggers:
creating a new team integration from an OAuth ``code``, reusing an existing
sibling install (``github/link_existing``), and minting a fresh OAuth URL when
the install flow returns without a code (``github/oauth_authorize``). Keeping
them out of the viewset lets the callback router compose the same logic.
"""

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.utils.crypto import get_random_string

import requests
import structlog
from rest_framework.exceptions import ValidationError

from posthog.api.github_callback.types import (
    GITHUB_INSTALL_STATE_CACHE_PREFIX,
    GITHUB_INSTALL_STATE_TTL_SECONDS,
    github_oauth_redirect_uri,
    is_valid_github_installation_id,
)
from posthog.models.integration import GitHubInstallationAccess, GitHubIntegration, Integration
from posthog.models.organization import Organization
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration, user_github_integration_from_installation
from posthog.utils import is_relative_url

logger = structlog.get_logger(__name__)

GITHUB_LINK_EXISTING_ERROR_ORPHAN_INSTALLATION = "github_link_existing_orphan_installation"
GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED = "github_link_existing_personal_github_required"
PERSONAL_GITHUB_REQUIRED_MESSAGE = (
    "You must connect your personal GitHub account (via Linked Accounts) before linking an existing "
    "installation, to confirm you have access to the GitHub App installation."
)


def installation_token_expires_at(integration: Integration) -> str:
    """Compute an ISO 8601 timestamp for when the integration's installation token expires."""
    refreshed_at = integration.config.get("refreshed_at", 0)
    expires_in = integration.config.get("expires_in", 3600)
    return datetime.fromtimestamp(refreshed_at + expires_in, tz=UTC).isoformat()


def create_team_github_integration_from_oauth_code(
    *,
    user: User,
    team_id: int,
    installation_id: Any | None,
    state_token: str | None,
    code: str | None,
) -> Integration:
    """Body of the ``IntegrationSerializer.create`` GitHub branch.

    Validates the cookie-paired server-side state token, exchanges the OAuth
    ``code`` for user-to-server tokens, verifies the user actually has access
    to ``installation_id`` on GitHub (so a stolen ``installation_id`` cannot
    mint repo tokens for someone else's org), then upserts the team
    ``Integration`` row and auto-creates a personal ``UserIntegration``.
    """
    if not installation_id:
        raise ValidationError("An installation_id must be provided")

    if not state_token:
        raise ValidationError("A state token must be provided")

    if not code:
        raise ValidationError("An OAuth code must be provided")

    cache_key = f"github_state:{user.id}"
    expected_state = cache.get(cache_key)
    if not expected_state or expected_state != state_token:
        raise ValidationError("Invalid or expired state token")
    cache.delete(cache_key)

    # Exchange the OAuth code for the user's access token and identity.
    # This requires GITHUB_APP_CLIENT_SECRET to be configured.
    authorization = GitHubIntegration.github_user_from_code(code)
    if authorization is None:
        raise ValidationError("Failed to exchange the OAuth code — ensure GITHUB_APP_CLIENT_SECRET is configured")

    # Verify the connecting user actually has access to this installation.
    # Without this, an attacker could supply another tenant's installation_id
    # with their own OAuth code and obtain an installation token scoped to
    # the other tenant's repos.
    if not is_valid_github_installation_id(installation_id):
        raise ValidationError("Invalid installation_id")
    try:
        has_access = GitHubIntegration.verify_user_installation_access(installation_id, authorization.access_token)
    except requests.RequestException:
        logger.warning(
            "github_integration_create: installation ownership check failed",
            installation_id=installation_id,
            user_id=user.id,
            exc_info=True,
        )
        raise ValidationError("Failed to verify installation access")
    if not has_access:
        logger.warning(
            "github_integration_create: user does not have access to installation",
            installation_id=installation_id,
            user_id=user.id,
        )
        raise ValidationError("You do not have access to this GitHub installation")

    instance = GitHubIntegration.integration_from_installation_id(installation_id, team_id, user)

    # Store the connecting user's GitHub login on the team integration
    # (shown on the integration card) and auto-create a UserIntegration
    # so the user immediately has personal GitHub credentials for
    # PR authorship and identity attribution
    instance.config["connecting_user_github_login"] = authorization.gh_login
    instance.save(update_fields=["config"])
    # Auto-create a UserIntegration so the user immediately has personal
    # GitHub credentials. create_only=True uses get_or_create atomically —
    # an existing personal integration (e.g. set up via Linked Accounts) is
    # left untouched even under concurrent requests.
    user_github_integration_from_installation(
        user,
        GitHubInstallationAccess(
            installation_id=installation_id,
            installation_info=instance.config,
            access_token=instance.sensitive_config.get("access_token", ""),
            token_expires_at=installation_token_expires_at(instance),
            repository_selection=instance.config.get("repository_selection", "selected"),
        ),
        authorization,
        create_only=True,
    )

    return instance


def link_existing_team_github_integration(
    *,
    user: User,
    organization: Organization,
    team_id: int,
    source_team_id: Any | None,
    installation_id_param: Any | None,
) -> Integration:
    """Reuse a GitHub installation already linked to a sibling team in the same organization."""
    if installation_id_param and not is_valid_github_installation_id(installation_id_param):
        raise ValidationError("Invalid installation_id")

    # installation_id is stored in JSONB and historically written as either a
    # string or a number, so match both representations.
    installation_id_match = (
        Q(config__installation_id=str(installation_id_param)) | Q(config__installation_id=int(installation_id_param))
        if installation_id_param
        else None
    )

    if source_team_id:
        try:
            source_team_id_int = int(source_team_id)
        except (TypeError, ValueError):
            raise ValidationError("source_team_id must be an integer")

        if not organization.teams.filter(id=source_team_id_int).exists():
            raise ValidationError("Source team not found in your organization")

        qs = Integration.objects.filter(team_id=source_team_id_int, kind="github")
        # When the source team has multiple GitHub installations linked, the
        # caller must pass installation_id to disambiguate.
        if installation_id_match is not None:
            qs = qs.filter(installation_id_match)

        source = qs.order_by("id").first()
        if source is None:
            raise ValidationError("Source team does not have a GitHub integration")
    elif installation_id_param:
        existing = (
            Integration.objects.filter(
                team__organization_id=organization.id,
                kind="github",
            )
            .filter(installation_id_match)
            .order_by("id")
            .first()
        )
        if existing is None:
            raise ValidationError(
                "No team in your organization has this GitHub installation linked",
                code=GITHUB_LINK_EXISTING_ERROR_ORPHAN_INSTALLATION,
            )
        source = existing
    else:
        raise ValidationError("source_team_id or installation_id is required")

    installation_id = (source.config or {}).get("installation_id")
    if not installation_id:
        raise ValidationError("Source integration is missing installation_id")

    # Confirms the requesting user has access to the installation on GitHub itself,
    # so cross-team admin access alone can't mint tokens for repos they can't see.
    user_github_integration = UserIntegration.objects.filter(user=user, kind="github").order_by("-created_at").first()
    user_access_token = (
        user_github_integration.sensitive_config.get("access_token") if user_github_integration else None
    )
    if not user_access_token:
        raise ValidationError(
            PERSONAL_GITHUB_REQUIRED_MESSAGE,
            code=GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED,
        )
    try:
        has_access = GitHubIntegration.verify_user_installation_access(str(installation_id), user_access_token)
    except requests.RequestException:
        logger.warning(
            "github_link_existing: installation ownership check failed",
            installation_id=installation_id,
            user_id=user.id,
            exc_info=True,
        )
        raise ValidationError("Failed to verify installation access")
    if not has_access:
        logger.warning(
            "github_link_existing: user does not have access to installation",
            installation_id=installation_id,
            user_id=user.id,
        )
        raise ValidationError(
            PERSONAL_GITHUB_REQUIRED_MESSAGE,
            code=GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED,
        )

    instance = GitHubIntegration.integration_from_installation_id(str(installation_id), team_id, user)

    source_login = (source.config or {}).get("connecting_user_github_login")
    if source_login and not (instance.config or {}).get("connecting_user_github_login"):
        instance.config["connecting_user_github_login"] = source_login
        instance.save(update_fields=["config"])

    return instance


def build_team_oauth_authorize_url(
    *,
    user_id: int,
    team_id: int,
    installation_id: Any | None,
    next_url: str,
    connect_from: str | None,
) -> str:
    """Mint a User OAuth URL to bootstrap a fresh ``code`` when the install flow returns without one."""
    if not installation_id:
        raise ValidationError("installation_id is required")

    if not is_valid_github_installation_id(installation_id):
        raise ValidationError("Invalid installation_id")

    # Open-redirect guard for the success-redirect to ``next``.
    if next_url and not is_relative_url(next_url):
        raise ValidationError("next must be a relative path starting with /")

    client_id = settings.GITHUB_APP_CLIENT_ID
    if not client_id:
        raise ValidationError("GitHub App client ID is not configured")

    token = get_random_string(48)
    state_payload: dict[str, Any] = {
        "user_id": user_id,
        "team_id": team_id,
        "installation_id": str(installation_id),
        "flow": "team_oauth_authorize",
        "next": next_url,
    }
    if connect_from:
        state_payload["connect_from"] = connect_from

    cache.set(
        f"{GITHUB_INSTALL_STATE_CACHE_PREFIX}{token}",
        state_payload,
        timeout=GITHUB_INSTALL_STATE_TTL_SECONDS,
    )

    return "https://github.com/login/oauth/authorize?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": github_oauth_redirect_uri(),
            "state": urlencode({"token": token}),
        }
    )
