"""
GitHub repository source support for business_knowledge.

Downloads public repositories as tarballs and extracts files matching
configurable path globs. Each matching file becomes a KnowledgeDocument.
"""

from __future__ import annotations

import os
import re
import json
import fnmatch
import tarfile
import posixpath
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from .constants import (
    GITHUB_CONNECT_TIMEOUT,
    GITHUB_DEFAULT_INCLUDE_GLOBS,
    GITHUB_MAX_DECOMPRESSED_BYTES,
    GITHUB_MAX_FILE_BYTES,
    GITHUB_MAX_MEMBERS,
    GITHUB_READ_TIMEOUT,
    GITHUB_TARBALL_MAX_BYTES,
    MAX_URLS_PER_SOURCE,
)
from .crawl import CrawlOutcome
from .url_fetch import UrlFetchError, fetch_stream, fetch_text, sha256_of

if TYPE_CHECKING:
    from .discover import CrawlConfig

logger = structlog.get_logger(__name__)


class GithubError(Exception):
    """User-safe error from GitHub operations."""


@dataclass(frozen=True)
class RepoInfo:
    """Parsed GitHub repository URL components."""

    owner: str
    repo: str
    ref: str | None
    subdir: str | None


_GITHUB_REPO_PATTERN = re.compile(
    r"^https?://github\.com/"
    r"(?P<owner>[^/]+)/"
    r"(?P<repo>[^/]+?)"
    r"(?:\.git)?"
    r"(?:/tree/(?P<ref>[^/]+)(?:/(?P<subdir>.+))?)?"
    r"/?$",
    re.IGNORECASE,
)


def parse_repo_url(url: str) -> RepoInfo:
    """
    Parse a GitHub URL into owner, repo, optional ref, and optional subdir.

    Accepts:
    - https://github.com/owner/repo
    - https://github.com/owner/repo.git
    - https://github.com/owner/repo/tree/branch
    - https://github.com/owner/repo/tree/branch/path/to/subdir

    Raises ``GithubError`` for non-GitHub URLs or invalid format.

    Limitation: a `/tree/<...>` URL is inherently ambiguous when the branch
    name contains `/` (e.g. `feature/x`). GitHub resolves this server-side; we
    can't, so we assume the first segment after `/tree/` is the ref and the rest
    is the subdir. `.../tree/feature/my-branch` is therefore read as
    ref=`feature`, subdir=`my-branch`. Prefer single-component refs
    (`main`, `v1.2.3`) — or pass a bare repo URL and set the ref separately.
    """

    match = _GITHUB_REPO_PATTERN.match(url.strip())
    if not match:
        raise GithubError("Not a valid GitHub repository URL.")

    owner = match.group("owner")
    repo = match.group("repo")
    ref = match.group("ref")
    subdir = match.group("subdir")

    if not owner or not repo:
        raise GithubError("Could not parse repository owner or name from URL.")

    if subdir:
        subdir = subdir.rstrip("/")

    return RepoInfo(owner=owner, repo=repo, ref=ref or None, subdir=subdir or None)


def resolve_ref(owner: str, repo: str, ref: str | None) -> str:
    """
    Resolve the ref (branch/tag) for a repository.

    If ``ref`` is provided, returns it as-is. Otherwise fetches the repo's
    default branch from the GitHub API (unauthenticated, 60 req/hr limit).

    Raises ``GithubError`` on failure.
    """

    if ref:
        return ref

    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        text = fetch_text(api_url, max_bytes=100_000)
        data = json.loads(text)
        default_branch = data.get("default_branch")
        if not default_branch:
            raise GithubError("Could not determine default branch.")
        return default_branch
    except UrlFetchError as exc:
        logger.warning(
            "business_knowledge.github.api_fetch_failed",
            owner=owner,
            repo=repo,
            error=str(exc),
        )
        raise GithubError("Could not fetch repository information. Is the repository public?") from exc
    except (json.JSONDecodeError, KeyError) as exc:
        raise GithubError("Invalid response from GitHub API.") from exc


def _matches_globs(path: str, include_globs: tuple[str, ...], exclude_globs: tuple[str, ...]) -> bool:
    """Check if a path matches include globs and doesn't match exclude globs."""

    basename = os.path.basename(path)
    matches_include = any(fnmatch.fnmatch(basename, g) or fnmatch.fnmatch(path, g) for g in include_globs)
    if not matches_include:
        return False
    matches_exclude = any(fnmatch.fnmatch(basename, g) or fnmatch.fnmatch(path, g) for g in exclude_globs)
    return not matches_exclude


def _normalize_member_path(name: str) -> str | None:
    """
    Normalize a tarball member path, stripping the leading repo-sha prefix.

    Returns None if the path escapes the repo root (path traversal attempt).
    """

    parts = name.split("/", 1)
    if len(parts) < 2:
        return None

    relative = parts[1]
    if not relative:
        return None

    normalized = posixpath.normpath(relative)
    if normalized.startswith("..") or normalized.startswith("/"):
        return None

    return normalized


def fetch_repo_files(
    owner: str,
    repo: str,
    ref: str,
    *,
    config: CrawlConfig,
    subdir: str | None = None,
) -> list[CrawlOutcome]:
    """
    Fetch a GitHub repository tarball and extract matching files.

    Streams the tarball through a gzip decompressor, filtering files by
    path globs. Each matching file becomes a ``CrawlOutcome``.

    Security guards:
    - Per-file size skip (``GITHUB_MAX_FILE_BYTES``): oversized files skipped
    - Compressed download cap (``GITHUB_TARBALL_MAX_BYTES``): aborts early
    - Decompressed stream cap (``GITHUB_MAX_DECOMPRESSED_BYTES``): bomb guard
    - Member count cap (``GITHUB_MAX_MEMBERS``): loop DoS guard
    - Path traversal rejection: escaping paths rejected
    - Regular files only: symlinks, devices, FIFOs ignored

    Args:
        owner: Repository owner
        repo: Repository name
        ref: Branch, tag, or commit SHA
        config: Crawl configuration with include/exclude globs and max_pages
        subdir: Optional subdirectory to scope extraction

    Returns:
        List of ``CrawlOutcome`` for each matching file.

    Raises:
        ``GithubError`` on fatal errors (network, too large, etc.)
    """

    tarball_url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}"

    include_globs = tuple(config.include_globs) if config.include_globs else GITHUB_DEFAULT_INCLUDE_GLOBS
    exclude_globs = tuple(config.exclude_globs) if config.exclude_globs else ()
    max_files = min(config.max_pages, MAX_URLS_PER_SOURCE)

    outcomes: list[CrawlOutcome] = []
    member_count = 0
    decompressed_bytes = 0

    try:
        with fetch_stream(
            tarball_url,
            max_bytes=GITHUB_TARBALL_MAX_BYTES,
            connect_timeout=GITHUB_CONNECT_TIMEOUT,
            read_timeout=GITHUB_READ_TIMEOUT,
        ) as stream:
            try:
                tf = tarfile.open(fileobj=stream, mode="r|gz")
            except tarfile.TarError as exc:
                raise GithubError("Failed to open repository archive.") from exc

            try:
                for member in tf:
                    member_count += 1

                    if member_count > GITHUB_MAX_MEMBERS:
                        raise GithubError("Repository archive has too many files.")

                    # Count every member's body against the global ceiling BEFORE any
                    # `continue` — tarfile decompresses a skipped member's bytes to
                    # advance the non-seekable gz stream, so a tarball of huge
                    # non-matching members must still be bounded (zip-bomb guard).
                    decompressed_bytes += member.size
                    if decompressed_bytes > GITHUB_MAX_DECOMPRESSED_BYTES:
                        raise GithubError("Repository archive exceeds size limits.")

                    if not member.isreg():
                        continue

                    normalized_path = _normalize_member_path(member.name)
                    if normalized_path is None:
                        logger.warning(
                            "business_knowledge.github.path_traversal_rejected",
                            owner=owner,
                            repo=repo,
                            member=member.name,
                        )
                        continue

                    if subdir and not normalized_path.startswith(subdir + "/"):
                        continue

                    display_path = normalized_path[len(subdir) + 1 :] if subdir else normalized_path

                    if not _matches_globs(display_path, include_globs, exclude_globs):
                        continue

                    if member.size > GITHUB_MAX_FILE_BYTES:
                        logger.info(
                            "business_knowledge.github.file_too_large",
                            owner=owner,
                            repo=repo,
                            path=normalized_path,
                            size=member.size,
                        )
                        continue

                    try:
                        extracted = tf.extractfile(member)
                        if extracted is None:
                            continue
                        content_bytes = extracted.read()
                    except (tarfile.TarError, OSError) as exc:
                        logger.warning(
                            "business_knowledge.github.extract_error",
                            owner=owner,
                            repo=repo,
                            path=normalized_path,
                            error=str(exc),
                        )
                        continue

                    try:
                        text = content_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        continue

                    blob_url = f"https://github.com/{owner}/{repo}/blob/{ref}/{normalized_path}"

                    outcomes.append(
                        CrawlOutcome(
                            url=blob_url,
                            final_url=blob_url,
                            status="ok",
                            title=display_path,
                            text=text,
                            content_hash=sha256_of(text),
                        )
                    )

                    if len(outcomes) >= max_files:
                        logger.info(
                            "business_knowledge.github.max_files_reached",
                            owner=owner,
                            repo=repo,
                            count=len(outcomes),
                        )
                        break
            finally:
                tf.close()

    except UrlFetchError as exc:
        logger.warning(
            "business_knowledge.github.tarball_fetch_failed",
            owner=owner,
            repo=repo,
            ref=ref,
            error=str(exc),
        )
        raise GithubError("Failed to download repository. Is it public?") from exc

    logger.info(
        "business_knowledge.github.extraction_complete",
        owner=owner,
        repo=repo,
        ref=ref,
        members_scanned=member_count,
        files_extracted=len(outcomes),
    )

    return outcomes
