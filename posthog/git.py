import re
import subprocess
from collections.abc import Iterator
from functools import cache
from typing import Optional
from urllib.parse import urlsplit

_git_commit_baked_in: Optional[str] = None
try:
    # Docker containers should have a commit.txt file in the base directory with the git
    # commit hash used to generate them.
    with open("commit.txt") as f:
        _git_commit_baked_in = f.read().strip()
except FileNotFoundError:
    pass


@cache
def get_git_commit_short() -> Optional[str]:
    """Return the short hash of the last commit.

    Example: get_git_commit_short() => "86a3c3b529"

    Cached: the commit cannot change within a running process, and callers on the
    request path (SLO events) would otherwise spawn a `git rev-parse` per request.
    """
    if _git_commit_baked_in:
        return _git_commit_baked_in[:10]  # 10 characters is almost guaranteed to identify a commit uniquely
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode("utf-8").strip()
    except Exception:
        return None


@cache
def get_git_branch() -> Optional[str]:
    """Returns the symbolic name of the current active branch. Will return None in case of failure.

    Example: get_git_branch() => "master"

    Cached for the same reason as get_git_commit_short.
    """

    try:
        return (
            subprocess.check_output(["git", "rev-parse", "--symbolic-full-name", "--abbrev-ref", "HEAD"])
            .decode("utf-8")
            .strip()
        )
    except Exception:
        return None


_TOKEN_PUNCTUATION = "`'\"()[]{}<>,.;:!?"
_GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
_REPO_TOKEN = re.compile(r"[\w.-]+/[\w.-]+")
# Slack formats links as <url|label> and either side can carry the repo, so `|` separates
# candidates the same way whitespace does.
_CANDIDATE_SEPARATOR = re.compile(r"[\s|]+")


def _repo_from_github_url(token: str) -> str | None:
    """`owner/repo` from a GitHub URL token, or None if it isn't one."""
    candidate = token.replace("git@github.com:", "https://github.com/", 1)
    if "//" not in candidate:
        candidate = f"https://{candidate}"  # urlsplit only populates netloc when a scheme is present
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return None
    # Exact host match, so `mygithub.com` and `github.com.evil.tld` can never resolve.
    if parts.hostname not in _GITHUB_HOSTS:
        return None
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) < 2:
        return None
    return f"{segments[0]}/{segments[1].removesuffix('.git')}"


def _candidates(text: str) -> Iterator[str]:
    for part in _CANDIDATE_SEPARATOR.split(text):
        candidate = part.strip(_TOKEN_PUNCTUATION)
        if candidate:
            yield candidate


def extract_explicit_repo(text: str, all_repos: list[str]) -> str | None:
    """Return the first bare `owner/repo` token in `text` that matches a connected repo.

    Matches case-insensitively and strips surrounding punctuation. `text` is assumed already
    cleaned of any platform-specific noise (e.g. bot mentions) by the caller.

    Pure helper (no Django / heavy deps) so any product can import it downward from core.
    """
    if not text or not all_repos:
        return None

    normalized_repos = {repo.lower(): repo for repo in all_repos}
    for candidate in _candidates(text):
        if _REPO_TOKEN.fullmatch(candidate) and (match := normalized_repos.get(candidate.lower())):
            return match
    return None


def extract_linked_repo(text: str, all_repos: list[str]) -> str | None:
    """Return the connected repo `text` links to, if it links to exactly one.

    Resolves a `github.com/owner/repo…` URL of any depth: a run, a pull request, a file
    permalink. Two different linked repos is genuine ambiguity and resolves to nothing, so a
    caller can fall back to asking rather than acting on whichever was pasted first.

    Weaker evidence than `extract_explicit_repo`, since a link can be in a message for reasons
    unrelated to the ask. Callers wanting both tiers take the typed token first.
    """
    if not text or not all_repos:
        return None

    normalized_repos = {repo.lower(): repo for repo in all_repos}
    linked = {
        match
        for candidate in _candidates(text)
        if (from_url := _repo_from_github_url(candidate)) and (match := normalized_repos.get(from_url.lower()))
    }
    return next(iter(linked)) if len(linked) == 1 else None


def extract_repo_from_scopes(scopes: list[str], all_repos: list[str]) -> str | None:
    """Return the repo named by the first of `scopes` to name one, a typed token beating a
    link within each scope. Callers order the scopes strongest evidence first.

    Each scope is matched on its own rather than joined into one string, which keeps the
    ambiguity rule in `extract_linked_repo` meaningful: two repos linked inside one scope is
    someone naming two things at once and resolves to nothing, while two repos linked across
    separate scopes is a thread accumulating links and lets the stronger scope answer.
    """
    for scope in scopes:
        if match := extract_explicit_repo(scope, all_repos) or extract_linked_repo(scope, all_repos):
            return match
    return None
