"""Exact-literal code search across a GitHub App installation's repositories.

GitHub's REST code search runs the legacy engine, which drops punctuation and ignores case, so a
quoted ``password-reset`` also finds ``password reset`` and ``Password_Reset``. Its results are
candidates only: each one is read and kept when the literal appears exactly.
"""

import re
from itertools import islice
from urllib.parse import quote

from posthog.dataclasses import frozen
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration.github import GitHubIntegration

MAX_CANDIDATE_FILES = 20
CONTEXT_LINES = 5
MAX_MATCHED_LINES_PER_FILE = 20
# GitHub caps search text at 256 characters, and the literal goes in quotes.
MAX_LITERAL_LENGTH = 254
_IDENTIFIER_CHARACTER = r"[A-Za-z0-9_-]"
_IGNORED_BY_GITHUB = re.compile(r'["\\]')


@frozen
class MatchedLine:
    number: int
    text: str
    context: str


@frozen
class ExactCodeMatch:
    repository: str
    path: str
    lines: tuple[MatchedLine, ...]


@frozen
class ExactCodeSearchResult:
    matches: list[ExactCodeMatch]
    complete: bool


class GitHubExactCodeSearch:
    def __init__(self, github: GitHubIntegration) -> None:
        self.github = github

    def find(self, literal: str) -> ExactCodeSearchResult:
        """Find the files in GitHub's index of each default branch that hold ``literal`` exactly.

        ``literal`` must not sit inside a longer run of letters, digits, ``_`` or ``-``. Each
        matched line comes with its text and up to ``CONTEXT_LINES`` lines on either side.
        ``complete`` is False when GitHub did not return every candidate, a candidate could not be
        read, or a file held more than ``MAX_MATCHED_LINES_PER_FILE`` matches, so a caller can tell
        "nowhere" from "not found in what was searched".
        Raises ``GitHubEgressBudgetExhausted`` when the egress lane sheds a request.
        """
        if not literal.strip() or len(literal) > MAX_LITERAL_LENGTH or literal.splitlines() != [literal]:
            raise ValueError(f"literal must be one line of 1 to {MAX_LITERAL_LENGTH} characters")
        body = self._search(literal)
        candidates = body.get("items") or []
        complete = not body.get("incomplete_results") and body.get("total_count", 0) <= len(candidates)
        pattern = re.compile(rf"(?<!{_IDENTIFIER_CHARACTER}){re.escape(literal)}(?!{_IDENTIFIER_CHARACTER})")

        matches: list[ExactCodeMatch] = []
        for candidate in candidates:
            repository = candidate["repository"]["full_name"]
            path = candidate["path"]
            try:
                file = self.github.get_file_contents(repository, quote(path))
            except (GitHubIntegrationError, UnicodeDecodeError):
                file = None
            if file is None:
                complete = False
                continue
            lines = self._matched_lines(file["content"].splitlines(), pattern)
            if len(lines) > MAX_MATCHED_LINES_PER_FILE:
                lines = lines[:MAX_MATCHED_LINES_PER_FILE]
                complete = False
            if lines:
                matches.append(ExactCodeMatch(repository=repository, path=path, lines=lines))
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

    @staticmethod
    def _matched_lines(file_lines: list[str], pattern: re.Pattern[str]) -> tuple[MatchedLine, ...]:
        matching = (index for index, line in enumerate(file_lines) if pattern.search(line))
        return tuple(
            MatchedLine(
                number=index + 1,
                text=file_lines[index],
                context="\n".join(file_lines[max(0, index - CONTEXT_LINES) : index + CONTEXT_LINES + 1]),
            )
            for index in islice(matching, MAX_MATCHED_LINES_PER_FILE + 1)
        )
