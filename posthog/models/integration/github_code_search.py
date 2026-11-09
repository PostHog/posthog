"""Exact-literal code search across a GitHub App installation's repositories.

GitHub's REST code search runs the legacy engine, which drops punctuation and ignores case, so a
quoted ``password-reset`` also finds ``password reset`` and ``Password_Reset``. Its results are
candidates only: each one is read and kept when the literal appears exactly.
"""

import re

from posthog.dataclasses import frozen
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration.github import GitHubIntegration

MAX_CANDIDATE_FILES = 20
_IDENTIFIER_CHARACTER = r"[A-Za-z0-9_-]"
_IGNORED_BY_GITHUB = re.compile(r'["\\]')


@frozen
class ExactCodeMatch:
    repository: str
    path: str
    blob_sha: str
    line_numbers: tuple[int, ...]


@frozen
class ExactCodeSearchResult:
    matches: list[ExactCodeMatch]
    complete: bool


class GitHubExactCodeSearch:
    def __init__(self, github: GitHubIntegration) -> None:
        self.github = github

    def find(self, literal: str) -> ExactCodeSearchResult:
        """Find the files on each repository's default branch that hold ``literal`` exactly.

        ``literal`` must not sit inside a longer run of letters, digits, ``_`` or ``-``.
        ``complete`` is False when GitHub did not return every candidate or a candidate could not
        be read, so a caller can tell "nowhere" from "not found in what was searched".
        Raises ``GitHubEgressBudgetExhausted`` when the egress lane sheds a request.
        """
        if not literal.strip():
            raise ValueError("literal must not be blank")
        body = self._search(literal)
        candidates = body.get("items") or []
        complete = not body.get("incomplete_results") and body.get("total_count", 0) <= len(candidates)
        pattern = re.compile(rf"(?<!{_IDENTIFIER_CHARACTER}){re.escape(literal)}(?!{_IDENTIFIER_CHARACTER})")

        matches: list[ExactCodeMatch] = []
        for candidate in candidates:
            repository = candidate["repository"]["full_name"]
            path = candidate["path"]
            try:
                file = self.github.get_file_contents(repository, path)
            except GitHubIntegrationError:
                file = None
            if file is None:
                complete = False
                continue
            line_numbers = tuple(
                number for number, line in enumerate(file["content"].splitlines(), start=1) if pattern.search(line)
            )
            if line_numbers:
                matches.append(
                    ExactCodeMatch(repository=repository, path=path, blob_sha=file["sha"], line_numbers=line_numbers)
                )
        return ExactCodeSearchResult(matches=matches, complete=complete)

    def _search(self, literal: str) -> dict:
        response = self.github.api_request(
            "GET",
            "/search/code",
            endpoint="/search/code",
            params={
                "q": f'"{_IGNORED_BY_GITHUB.sub(" ", literal)}" {self._account_qualifier()}',
                "per_page": MAX_CANDIDATE_FILES,
            },
        )
        if response.status_code != 200:
            raise GitHubIntegrationError(
                f"GitHubExactCodeSearch: code search failed: {response.text[:300]}", status_code=response.status_code
            )
        return response.json()

    def _account_qualifier(self) -> str:
        account_type = self.github.integration.config.get("account", {}).get("type")
        qualifier = "org" if account_type == "Organization" else "user"
        return f"{qualifier}:{self.github.organization()}"
