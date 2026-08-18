"""Shared recording of a personal GitHub App install pending org-owner approval.

GitHub sends the user back with ``setup_action=request`` (no ``installation_id``) when the
account installing the App isn't an org owner. Both the personal-connect flow
(``personal_finish.finish_personal``) and the team-connect flow (``team_services.finish_team_setup``)
hit this branch, so the row-write lives here once. See ``posthog.models.user_integration.GitHubInstallRequest``
for why this needs to be durable server-side state rather than a client-held marker.
"""

import requests
import structlog

from posthog.models.integration import GitHubIntegration
from posthog.models.user import User
from posthog.models.user_integration import GitHubInstallRequest

logger = structlog.get_logger(__name__)


def record_install_request(user: User, code: str | None, *, redirect_uri: str | None = None) -> None:
    """Upsert a pending ``GitHubInstallRequest`` for ``user``, resolving a login from ``code`` if present.

    Never raises: a missing or unusable ``code`` still records the request, with an empty
    ``github_login``, rather than dropping the wait state entirely. The callback redirect must
    proceed either way.
    """
    login = ""
    if code:
        try:
            authorization = GitHubIntegration.github_user_from_code(code, redirect_uri=redirect_uri)
        except requests.RequestException:
            authorization = None
        if authorization is not None:
            login = authorization.gh_login
        else:
            logger.warning(
                "github_install_request: code exchange failed while recording pending request", user_id=user.id
            )
    else:
        logger.warning("github_install_request: no code present while recording pending request", user_id=user.id)

    GitHubInstallRequest.objects.get_or_create(
        user=user,
        github_login=login,
        status=GitHubInstallRequest.Status.PENDING,
    )
