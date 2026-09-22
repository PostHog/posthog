"""Shared recording of a personal GitHub App install pending org-owner approval.

GitHub sends the user back with ``setup_action=request`` (no ``installation_id``) when the
account installing the App isn't an org owner. Both the personal-connect flow
(``personal_finish.finish_personal``) and the team-connect flow (``team_services.finish_team_setup``)
hit this branch, so the row-write lives here once. See ``posthog.models.user_integration.GitHubInstallRequest``
for why this needs to be durable server-side state rather than a client-held marker.
"""

import requests
import structlog

from posthog.models.integration import GitHubIntegration, GitHubUserAuthorization
from posthog.models.user import User
from posthog.models.user_integration import GitHubInstallRequest

logger = structlog.get_logger(__name__)


def record_install_request(user: User, code: str | None, *, redirect_uri: str | None = None) -> None:
    """Upsert a ``GitHubInstallRequest`` for ``user``, resolving the requester from ``code``.

    The ``installation.created`` webhook identifies the requester by GitHub user id, so a request
    we cannot resolve an id for is recorded as ``unidentified`` instead of ``pending`` — nothing
    could ever flip it, and a client polling ``pending`` would wait forever. Never raises: the
    callback redirect must proceed either way.
    """
    authorization = _requester_from_code(user, code, redirect_uri)
    if authorization is None:
        GitHubInstallRequest.objects.get_or_create(
            user=user,
            github_user_id=None,
            status=GitHubInstallRequest.Status.UNIDENTIFIED,
        )
        return

    GitHubInstallRequest.objects.update_or_create(
        user=user,
        github_user_id=authorization.gh_id,
        status=GitHubInstallRequest.Status.PENDING,
        defaults={"github_login": authorization.gh_login},
    )


def _requester_from_code(user: User, code: str | None, redirect_uri: str | None) -> GitHubUserAuthorization | None:
    if not code:
        logger.warning("github_install_request: no code to identify the requester with", user_id=user.id)
        return None

    try:
        authorization = GitHubIntegration.github_user_from_code(code, redirect_uri=redirect_uri)
    except (requests.RequestException, ValueError):
        # ValueError: GitHub answered 200 with a non-JSON body (outage page, proxy
        # interstitial); the callback redirect must still proceed.
        authorization = None
    if authorization is None:
        logger.warning("github_install_request: code exchange could not identify the requester", user_id=user.id)
    return authorization
