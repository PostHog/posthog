"""GitHub adapter boundary.

The rest of Deployments talks to GitHub through this module. For the
hackathon path, repository selection uses the existing PostHog
``Integration(kind="github")`` installation rather than a Deployments-specific
GitHub App or live push webhooks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import quote

from django.conf import settings

from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration

from ..domain.contracts import CommitMetadata

if TYPE_CHECKING:
    from posthog.models.integration import Integration


_REPO_FULL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

# TODO(deployments-v1): move request-path GitHub verification to async jobs before increasing retry budgets.
DEPLOYMENTS_GITHUB_API_TIMEOUT_SECONDS = 2


@dataclass(frozen=True)
class GitHubRepository:
    id: int
    full_name: str
    default_branch: str
    html_url: str


@dataclass(frozen=True)
class GitHubBranch:
    name: str
    sha: str


class GitHubAdapter(Protocol):
    """Surface we depend on from GitHub.

    The build worker resolves a commit SHA off the request path — if the
    API request didn't pin one — by calling `head_of_branch`. The API
    itself rarely needs `get_commit`; we expose it because the GitHub
    stream may want to populate commit metadata on the Deployment row at
    create-time (cheaper than waiting for the worker to fill it in).

    `access_token` is the short-lived GitHub App installation token resolved
    by `create_deployment` from the project's `posthog.Integration` row.
    None means unauthenticated (public repos only).
    """

    def head_of_branch(self, *, repo_url: str, branch: str, access_token: str | None) -> CommitMetadata: ...

    def get_commit(self, *, repo_url: str, sha: str, access_token: str | None) -> CommitMetadata: ...

    def get_repository_by_id(self, *, integration: Integration, github_repo_id: int) -> GitHubRepository: ...

    def get_repository(self, *, integration: Integration, repo_full_name: str) -> GitHubRepository: ...

    def get_branch(self, *, integration: Integration, repo_full_name: str, branch: str) -> GitHubBranch: ...


class GitHubError(Exception):
    """Raised when a GitHub API call fails. Translated by callers."""


def validate_repo_full_name(repo_full_name: str) -> None:
    if not _REPO_FULL_NAME_RE.fullmatch(repo_full_name):
        raise GitHubError("Repository must be in owner/repo format.")
    owner, repo = repo_full_name.split("/", 1)
    if owner in (".", "..") or repo in (".", ".."):
        raise GitHubError("Repository must be in owner/repo format.")


def repo_url_from_full_name(repo_full_name: str) -> str:
    validate_repo_full_name(repo_full_name)
    return f"https://github.com/{repo_full_name}"


class NullGitHubAdapter:
    """Stub used in tests and the dev environment for deployment commits.

    Repository/branch selection is implemented by ``GitHubIntegrationAdapter``
    below because it uses the existing Integration installation token. Commit
    resolution remains synthetic until the build stream wires the full clone
    credentials contract.
    """

    def head_of_branch(self, *, repo_url: str, branch: str, access_token: str | None) -> CommitMetadata:
        return CommitMetadata(
            sha="0" * 40,
            message="chore: stubbed commit (NullGitHubAdapter)",
            author_name="Test Author",
            author_email="test@posthog.com",
            branch=branch,
        )

    def get_commit(self, *, repo_url: str, sha: str, access_token: str | None) -> CommitMetadata:
        return CommitMetadata(
            sha=sha,
            message="chore: stubbed commit (NullGitHubAdapter)",
            author_name="Test Author",
            author_email="test@posthog.com",
            branch="main",
        )

    def get_repository_by_id(self, *, integration: Integration, github_repo_id: int) -> GitHubRepository:
        return GitHubRepository(
            id=github_repo_id,
            full_name="example-org/site",
            default_branch="main",
            html_url="https://github.com/example-org/site",
        )

    def get_repository(self, *, integration: Integration, repo_full_name: str) -> GitHubRepository:
        validate_repo_full_name(repo_full_name)
        return GitHubRepository(
            id=0,
            full_name=repo_full_name,
            default_branch="main",
            html_url=repo_url_from_full_name(repo_full_name),
        )

    def get_branch(self, *, integration: Integration, repo_full_name: str, branch: str) -> GitHubBranch:
        validate_repo_full_name(repo_full_name)
        return GitHubBranch(name=branch, sha="0" * 40)


class GitHubIntegrationAdapter(NullGitHubAdapter):
    """GitHub adapter backed by the existing PostHog GitHub integration."""

    def _get_json(self, *, integration: Integration, path: str, endpoint: str) -> dict[str, Any]:
        try:
            payload = GitHubIntegration(integration)._gh_api_get(
                path,
                endpoint=endpoint,
                timeout=DEPLOYMENTS_GITHUB_API_TIMEOUT_SECONDS,
            )
        except GitHubIntegrationError as err:
            raise GitHubError(str(err)) from err
        if not isinstance(payload, dict):
            raise GitHubError("GitHub API returned an unexpected response shape.")
        return payload

    def _repository_from_payload(self, payload: dict[str, Any]) -> GitHubRepository:
        repository_id = payload.get("id")
        full_name = payload.get("full_name")
        default_branch = payload.get("default_branch")
        html_url = payload.get("html_url")
        if not isinstance(repository_id, int):
            raise GitHubError("GitHub repository response was missing a valid id.")
        if not isinstance(full_name, str) or not full_name:
            raise GitHubError("GitHub repository response was missing a full_name.")
        if not isinstance(default_branch, str) or not default_branch:
            raise GitHubError("GitHub repository response was missing a default branch.")
        if not isinstance(html_url, str) or not html_url:
            html_url = repo_url_from_full_name(full_name)

        return GitHubRepository(
            id=repository_id,
            full_name=full_name,
            default_branch=default_branch,
            html_url=html_url,
        )

    def get_repository_by_id(self, *, integration: Integration, github_repo_id: int) -> GitHubRepository:
        payload = self._get_json(
            integration=integration,
            path=f"/repositories/{github_repo_id}",
            endpoint="/repositories/{repository_id}",
        )
        repository = self._repository_from_payload(payload)
        if repository.id != github_repo_id:
            raise GitHubError("GitHub repository response id did not match the requested repository.")
        return repository

    def get_repository(self, *, integration: Integration, repo_full_name: str) -> GitHubRepository:
        validate_repo_full_name(repo_full_name)
        payload = self._get_json(
            integration=integration,
            path=f"/repos/{repo_full_name}",
            endpoint="/repos/{owner}/{repo}",
        )

        return self._repository_from_payload(payload)

    def get_branch(self, *, integration: Integration, repo_full_name: str, branch: str) -> GitHubBranch:
        validate_repo_full_name(repo_full_name)
        if not branch:
            raise GitHubError("A tracked branch is required.")
        payload = self._get_json(
            integration=integration,
            path=f"/repos/{repo_full_name}/branches/{quote(branch, safe='')}",
            endpoint="/repos/{owner}/{repo}/branches/{branch}",
        )

        branch_name = payload.get("name")
        commit = payload.get("commit")
        sha = commit.get("sha") if isinstance(commit, dict) else None
        if not isinstance(branch_name, str) or not branch_name:
            branch_name = branch
        if not isinstance(sha, str) or not sha:
            raise GitHubError("GitHub branch response was missing a commit SHA.")
        return GitHubBranch(name=branch_name, sha=sha)


def get_github_adapter() -> GitHubAdapter:
    path = getattr(settings, "DEPLOYMENTS_GITHUB_ADAPTER", None)
    if not path:
        return GitHubIntegrationAdapter()
    module_path, class_name = path.split(":")
    module = import_module(module_path)
    return getattr(module, class_name)()
