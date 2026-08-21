"""Parsing of GitHub issue and pull request references pasted by support teammates."""

import re
from urllib.parse import urlparse

from posthog.dataclasses import frozen

from products.conversations.backend.models.ticket_github_link import TicketGithubLinkType

GITHUB_HOSTS = {"github.com", "www.github.com"}
# GitHub never allows an owner or repo name made only of dots, and letting one through ("..", ".")
# would let dot-segment normalization steer the /repos/{owner}/{repo}/... API path elsewhere.
_REPO_PART = r"(?!\.+(?:/|#|$))[A-Za-z0-9._-]+"
_REPO_PART_RE = re.compile(rf"^{_REPO_PART}$")
# owner/repo#123, the shorthand GitHub itself renders for cross-repo references.
_SHORTHAND_RE = re.compile(rf"^(?P<owner>{_REPO_PART})/(?P<repo>{_REPO_PART})#(?P<number>[1-9][0-9]*)$")
_LINK_TYPE_BY_PATH_SEGMENT = {
    "issues": TicketGithubLinkType.ISSUE,
    "pull": TicketGithubLinkType.PULL_REQUEST,
    "pulls": TicketGithubLinkType.PULL_REQUEST,
}


@frozen
class GithubReference:
    repo: str
    number: int
    # None when the input doesn't say (shorthand form); the GitHub API resolves it if an integration
    # can see the repo, otherwise it's stored as an issue, which GitHub redirects to the PR page anyway.
    link_type: TicketGithubLinkType | None


def parse_github_reference(value: str) -> GithubReference | None:
    """Parse a GitHub issue/PR URL or ``owner/repo#123`` shorthand, or None if it's neither."""
    text = value.strip()
    shorthand = _SHORTHAND_RE.match(text)
    if shorthand:
        return GithubReference(
            repo=f"{shorthand['owner']}/{shorthand['repo']}", number=int(shorthand["number"]), link_type=None
        )

    try:
        parsed = urlparse(text)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in GITHUB_HOSTS:
        return None

    parts = [p for p in parsed.path.split("/") if p]
    # Expected path: /{owner}/{repo}/{issues|pull}/{number}[/...]
    if len(parts) < 4:
        return None
    owner, repo, segment, number_str = parts[:4]
    if not _REPO_PART_RE.match(owner) or not _REPO_PART_RE.match(repo):
        return None
    link_type = _LINK_TYPE_BY_PATH_SEGMENT.get(segment)
    if link_type is None or not number_str.isdigit() or int(number_str) == 0:
        return None

    return GithubReference(repo=f"{owner}/{repo}", number=int(number_str), link_type=link_type)
