"""The GitHub calls commands make, through the PostHog GitHub App installation of the pull request.

Reads raise ``GitHubCallFailed`` so dispatch can fail closed. Reactions and replies are best effort:
a lost acknowledgement must not stop a command or turn a run that started into a failure.
"""

import re
from collections.abc import Collection
from typing import Literal, Protocol

import requests
import structlog

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationManager
from posthog.models.integration import GitHubIntegration, GitHubIntegrationError

from .commands import REPOSITORY_NAME_RE, PullRequestFacts

logger = structlog.get_logger(__name__)

Reaction = Literal["eyes", "rocket"]

_SOURCE = "commands"

# The branch name goes into an agent prompt and a loop payload, so only a plain identifier passes.
_BRANCH_NAME_RE = re.compile(r"[A-Za-z0-9._/-]{1,255}")

_CALL_ERRORS = (GitHubIntegrationError, GitHubRateLimitError, requests.RequestException)


class GitHubCallFailed(Exception):
    """A read GitHub did not answer, so the caller cannot tell what the answer would have been."""


class UnsupportedPullRequest(Exception):
    """The pull request's names are not plain identifiers, so no command may pass them on."""


class CommandGitHub(Protocol):
    def collaborator_permission(self, repository: str, login: str, github_user_id: int) -> str: ...

    def pull_request(self, repository: str, number: int) -> PullRequestFacts | None: ...

    def react(self, repository: str, comment_id: int, reaction: Reaction) -> None: ...

    def reply(self, repository: str, number: int, body: str) -> None: ...


class InstallationGitHub:
    def __init__(self, client: GitHubIntegration) -> None:
        self._client = client

    @classmethod
    def for_installation(cls, installation_id: str, team_ids: Collection[int]) -> "InstallationGitHub | None":
        """A client on the installation, through the row of one of ``team_ids``.

        Every row mints the same installation token, but minting saves the token on the row and a
        failed refresh marks the row with an error. Passing the projects that turned commands on keeps
        those writes off projects that never did. The project a command runs in is picked later.
        """
        # nosemgrep: github-installation-first-team -- any of the given projects serves, see the docstring
        rows = IntegrationManager.github.oauth.list_by_external_id(installation_id, team_ids=team_ids)
        if not rows:
            return None
        integration = min(rows, key=lambda row: row.id)
        return cls(GitHubIntegration(integration, source=_SOURCE, priority=Priority.CRITICAL))

    def collaborator_permission(self, repository: str, login: str, github_user_id: int) -> str:
        try:
            return self._client.get_collaborator_permission(repository, login, expected_user_id=github_user_id)
        except _CALL_ERRORS as error:
            raise GitHubCallFailed from error

    def pull_request(self, repository: str, number: int) -> PullRequestFacts | None:
        try:
            pr = self._client.get_pull_request(repository, number)
        except _CALL_ERRORS as error:
            raise GitHubCallFailed from error
        if not pr.get("success"):
            return None
        head_repository = pr.get("head_repository")
        head_sha = pr.get("head_sha")
        head_branch = pr.get("head_branch")
        url = pr.get("url")
        if not (isinstance(head_sha, str) and isinstance(head_branch, str) and isinstance(url, str)):
            return None
        if not (_BRANCH_NAME_RE.fullmatch(head_branch) and REPOSITORY_NAME_RE.fullmatch(repository)):
            raise UnsupportedPullRequest
        return PullRequestFacts(
            repository=repository,
            number=number,
            url=url,
            state="merged" if pr.get("merged") else str(pr.get("state") or ""),
            draft=bool(pr.get("draft")),
            head_sha=head_sha,
            head_branch=head_branch,
            # A deleted fork reports no head repository, which is no more trustworthy than a fork.
            is_fork=not isinstance(head_repository, str) or head_repository.lower() != repository.lower(),
        )

    def react(self, repository: str, comment_id: int, reaction: Reaction) -> None:
        try:
            response = self._client.api_request(
                "POST",
                f"/repos/{repository}/issues/comments/{comment_id}/reactions",
                endpoint="/repos/{owner}/{repo}/issues/comments/{comment_id}/reactions",
                json_body={"content": reaction},
            )
        except _CALL_ERRORS:
            logger.warning("github_command_reaction_failed", exc_info=True)
            return
        if response.status_code not in (200, 201):
            logger.warning("github_command_reaction_failed", status_code=response.status_code)

    def reply(self, repository: str, number: int, body: str) -> None:
        try:
            result = self._client.comment_on_pull_request(repository, number, body)
        except _CALL_ERRORS:
            logger.warning("github_command_reply_failed", exc_info=True)
            return
        if not result.get("success"):
            logger.warning("github_command_reply_failed", status_code=result.get("status_code"))
