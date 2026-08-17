import re
import subprocess
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


def extract_explicit_repo(text: str, all_repos: list[str]) -> str | None:
    """Return the connected repo `text` names: the first one typed, or the only one linked.

    Two tiers of evidence, strongest first: a bare `owner/repo` token, then a
    `github.com/owner/repo…` URL of any depth (a run, a pull request, a file permalink).
    Typing a repo out is more deliberate than pasting a link that happens to be in the
    message, so a bare token wins outright. `text` is assumed already cleaned of any
    platform-specific noise (e.g. bot mentions) by the caller.

    Links only resolve when the message points at a single connected repo. Two different
    linked repos is genuine ambiguity, and None is the answer every caller can act on:
    Slack falls through to its discovery agent and then a repo picker, and the callers
    with no such fallback start repo-less rather than on whichever was pasted first. A
    link someone labeled `<url|owner/repo>` reads as a typed token and wins outright;
    Slack writes its own labels as `github.com/owner/repo/…`, which read as links.

    Pure helper (no Django / heavy deps) so any product can import it downward from core.
    """
    if not text or not all_repos:
        return None

    normalized_repos = {repo.lower(): repo for repo in all_repos}
    linked: set[str] = set()

    for part in _CANDIDATE_SEPARATOR.split(text):
        candidate = part.strip(_TOKEN_PUNCTUATION)
        if not candidate:
            continue

        if _REPO_TOKEN.fullmatch(candidate) and (match := normalized_repos.get(candidate.lower())):
            return match

        from_url = _repo_from_github_url(candidate)
        if from_url and (match := normalized_repos.get(from_url.lower())):
            linked.add(match)

    return next(iter(linked)) if len(linked) == 1 else None


def extract_explicit_repo_from_scopes(scopes: list[str], all_repos: list[str]) -> str | None:
    """Return the connected repo named by the first of `scopes` to name one.

    Callers order `scopes` strongest evidence first, so the text someone wrote while asking
    beats the text that happened to be nearby.

    Each scope is matched on its own rather than joined into one string, which is what keeps
    the ambiguity rule in `extract_explicit_repo` meaningful. Two repos named inside a single
    scope is one person naming two things at once, so nothing resolves. Two repos named across
    separate scopes is an ordinary thread accumulating links, so the stronger scope answers.
    Joining them first would collapse that distinction and make a long thread resolve to
    nothing almost every time.
    """
    for scope in scopes:
        if match := extract_explicit_repo(scope, all_repos):
            return match
    return None
