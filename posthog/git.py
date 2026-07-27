import re
import subprocess
from functools import cache
from typing import Optional

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


def extract_explicit_repo(text: str, all_repos: list[str]) -> str | None:
    """Return the first explicit `owner/repo` token in `text` that matches a connected repo.

    Tokenizes on whitespace and matches bare `owner/repo` tokens (no `@` prefix needed)
    case-insensitively against `all_repos`. Strips surrounding punctuation and handles
    Slack's `<url|label>` link form. `text` is assumed already cleaned of any
    platform-specific noise (e.g. bot mentions) by the caller.

    Pure helper (no Django / heavy deps) so any product can import it downward from core.
    """
    if not text or not all_repos:
        return None

    normalized_repos = {repo.lower(): repo for repo in all_repos}

    for token in text.split():
        candidate = token.strip("`'\"()[]{}<>,.;:!?")

        # Slack can format links as <url|label>; for repo tokens we want the label.
        if "|" in candidate:
            candidate = candidate.split("|", 1)[1].strip("`'\"()[]{}<>,.;:!?")

        if not candidate or "://" in candidate or candidate.startswith("http"):
            continue
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", candidate):
            continue

        match = normalized_repos.get(candidate.lower())
        if match:
            return match

    return None
