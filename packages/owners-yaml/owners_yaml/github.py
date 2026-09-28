"""Live checks of owners against a GitHub organization, through the ``gh`` CLI."""

from __future__ import annotations

import shutil
import subprocess


class GitHubLookupError(Exception):
    """The ``gh`` CLI is missing, failed, or timed out."""


class GitHubOrg:
    """Team slugs and members of one GitHub organization.

    Team slugs are fetched once per instance, and a failed fetch is not retried, so a caller that
    checks many files waits for one timeout at most.

    The lookup uses ``/orgs/{org}/teams``, which needs ``members: read``. The repo-level teams
    endpoint would be a tighter check, because only teams with repo access can review, but many
    app tokens lack that scope.
    """

    def __init__(self, org: str, timeout_seconds: int = 15) -> None:
        self.org = org
        self.timeout_seconds = timeout_seconds
        self._team_slugs: set[str] | None = None
        self._team_slugs_error: GitHubLookupError | None = None

    def _gh_api(self, *args: str) -> subprocess.CompletedProcess[str]:
        if not shutil.which("gh"):
            raise GitHubLookupError("gh CLI not found; install it to validate owners against GitHub")
        try:
            return subprocess.run(
                ["gh", "api", *args],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitHubLookupError(f"gh api timed out after {self.timeout_seconds}s") from exc

    def _fetch_team_slugs(self) -> set[str]:
        result = self._gh_api(f"orgs/{self.org}/teams", "--paginate", "--jq", ".[].slug")
        if result.returncode != 0 or not result.stdout.strip():
            raise GitHubLookupError(f"gh api failed (rc={result.returncode}): {result.stderr.strip()}")
        return set(result.stdout.strip().split("\n"))

    def team_slugs(self) -> set[str]:
        if self._team_slugs_error is not None:
            raise self._team_slugs_error
        if self._team_slugs is None:
            try:
                self._team_slugs = self._fetch_team_slugs()
            except GitHubLookupError as exc:
                self._team_slugs_error = exc
                raise
        return self._team_slugs

    def is_member(self, handle: str) -> bool:
        """Org membership, not only account existence: a review request to a non-member fails."""
        return self._gh_api(f"orgs/{self.org}/members/{handle}").returncode == 0
