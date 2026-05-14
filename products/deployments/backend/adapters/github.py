"""GitHub adapter boundary.

The GitHub auth stream owns the real implementation (resolves HEAD of a
branch, fetches commit metadata, exchanges PAT/OAuth). We declare the
Protocol they implement against and a Null stub for tests.
"""

from __future__ import annotations

from importlib import import_module
from typing import Protocol

from django.conf import settings

from ..domain.contracts import CommitMetadata


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


class GitHubError(Exception):
    """Raised when a GitHub API call fails. Translated to 502 by callers."""


class NullGitHubAdapter:
    """Stub used in tests and the dev environment.

    Returns synthetic commit metadata that mirrors the shape of a real
    response. The author email matches the test team's owner email pattern
    so author-filter tests can assert against a stable value.
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


def get_github_adapter() -> GitHubAdapter:
    path = getattr(settings, "DEPLOYMENTS_GITHUB_ADAPTER", None)
    if not path:
        return NullGitHubAdapter()
    module_path, class_name = path.split(":")
    module = import_module(module_path)
    return getattr(module, class_name)()
