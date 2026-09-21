"""A repository's ownership files read from the GitHub API with a credential.

The raw host in ``repo_files`` serves public repositories only, and it costs one request per file.
This module reads the same files through the GitHub GraphQL API, which authenticates, answers for a
private repository, and returns about a hundred files per request.

Every read is pinned to the default branch's head commit. The content at a commit never changes, so
the cache can hold it for days, and a merge is visible as soon as the short-lived head lookup
expires. The raw host cannot name a commit, so it keeps its own cache and its own six-hour staleness
window.
"""

import hashlib
from collections.abc import Callable, Iterable, Sequence
from http import HTTPStatus
from time import monotonic
from typing import Any

from django.core.cache import cache

import requests
from requests.adapters import HTTPAdapter

from posthog.egress.github.transport import github_request
from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration
from posthog.models.integration.github import _is_safe_github_repo_path
from posthog.ownership.repo_files import (
    _ABSENT,
    _FETCH_WORKERS,
    _MAX_FILE_BYTES,
    _RESOLVE_BUDGET_SECONDS,
    GitHubRepoFiles,
    OwnershipUnavailable,
    RepoFiles,
    _fetch_all,
)

_API_HOST = "https://api.github.com"
_GRAPHQL_URL = f"{_API_HOST}/graphql"
# A separate label from the raw host's, because these calls are authenticated and land on a
# different meter. Renaming either one would break the dashboards that already query them.
_EGRESS_SOURCE = "ownership_github_api"
_HEAD_ENDPOINT = "/graphql:ownershipHeadCommit"
_FILES_ENDPOINT = "/graphql:ownershipFiles"
_TIMEOUT_SECONDS = 10.0

# GitHub charges one rate-limit point for a whole aliased query, so the files of a batch cost one
# point per chunk. The ceiling is latency and the server's own limits: this repo answers about a
# hundred files in a few seconds and refuses four hundred with a 502.
_CHUNK_FILES = 100

_CACHE_PREFIX = "ownership:github_api"
# A commit's content is immutable, so the only reason to expire a blob is to release the memory.
# No jitter: a whole batch expiring together can only stampede for a commit that nothing has read
# for a week, and that answer is worth refetching anyway.
_BLOB_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
# Short, because this is the whole staleness window of an ownership change. Long enough that a burst
# of page loads asks GitHub for the head once rather than once each.
_HEAD_CACHE_TTL_SECONDS = 120

_HEAD_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { oid } }
  }
}
"""

# Each file is one aliased `object` lookup. The path rides in a variable rather than in the query
# text, so a path can never change the shape of the query.
_TEXT_SELECTION = "... on Blob { text }"
_EXISTS_SELECTION = "__typename"


def _token_audience(token: str) -> str:
    """A stable name for what one token is allowed to read.

    Two credentials must never share cached file content: a private repository one installation can
    read is not readable by the next caller that names the same repository. The token itself must
    stay out of the key, so the key carries a digest of it.
    """
    return f"token:{hashlib.sha256(token.encode()).hexdigest()[:16]}"


def _files_query(count: int, selection: str) -> str:
    variables = ", ".join(f"$p{index}: String!" for index in range(count))
    fields = "\n".join(f"    f{index}: object(expression: $p{index}) {{ {selection} }}" for index in range(count))
    return f"query($owner: String!, $name: String!, {variables}) {{\n  repository(owner: $owner, name: $name) {{\n{fields}\n  }}\n}}"


def _chunks(paths: Sequence[str]) -> list[tuple[str, ...]]:
    return [tuple(paths[start : start + _CHUNK_FILES]) for start in range(0, len(paths), _CHUNK_FILES)]


def _entry(field: dict[str, Any], index: int) -> dict[str, Any] | None:
    entry = field.get(f"f{index}")
    return entry if isinstance(entry, dict) else None


class GitHubFilesFetcher:
    """Reads a repository's files from the GitHub GraphQL API with one credential.

    Build one with :meth:`from_integration` or :meth:`from_token`. It holds the batch's HTTP
    connections and its token, so construct one per batch.
    """

    @classmethod
    def from_integration(cls, integration: GitHubIntegrationBase, *, priority: Priority) -> "GitHubFilesFetcher":
        """Read as a GitHub App installation, which is what a connected team already has."""
        installation_id = integration.github_installation_id
        return cls(
            token=integration.get_access_token,
            installation_id=installation_id,
            audience=(
                f"installation:{installation_id}"
                if installation_id
                else f"integration:{type(integration.integration).__name__}:{integration.integration.pk}"
            ),
            priority=priority,
        )

    @classmethod
    def from_token(cls, token: str, *, installation_id: str | None = None, priority: Priority) -> "GitHubFilesFetcher":
        """Read with a token the caller already holds: a personal access token, or an installation
        token minted by a product's own GitHub App. Pass ``installation_id`` when the token belongs
        to an installation, so the calls are gated on that installation's shared budget."""
        return cls(
            token=lambda: token,
            installation_id=installation_id,
            audience=f"installation:{installation_id}" if installation_id else _token_audience(token),
            priority=priority,
        )

    def __init__(
        self,
        *,
        token: Callable[[], str],
        installation_id: str | None,
        audience: str,
        priority: Priority,
    ) -> None:
        self.audience = audience
        self._token = token
        self._resolved_token: str | None = None
        self._installation_id = installation_id
        self._priority = priority
        self._session = requests.Session()
        # requests pools ten connections by default and discards the overflow, so a smaller pool than
        # the worker count makes most of a batch pay a fresh TLS handshake.
        self._session.mount(_API_HOST, HTTPAdapter(pool_connections=_FETCH_WORKERS, pool_maxsize=_FETCH_WORKERS))

    def head_commit_sha(self, repository: str) -> str:
        """The commit at the head of the repository's default branch."""
        field = self._graphql(repository, _HEAD_QUERY, {}, endpoint=_HEAD_ENDPOINT)
        ref = field.get("defaultBranchRef")
        target = ref.get("target") if isinstance(ref, dict) else None
        sha = target.get("oid") if isinstance(target, dict) else None
        if not isinstance(sha, str) or not sha:
            raise OwnershipUnavailable(f"{repository} named no default branch head")
        return sha

    def read_files(self, repository: str, sha: str, paths: Sequence[str], deadline: float) -> dict[str, str]:
        """The text of every path at ``sha``, with ``_ABSENT`` for a path the commit does not hold."""
        return self._read_chunks(repository, sha, paths, deadline, _TEXT_SELECTION, self._text)

    def files_exist(self, repository: str, sha: str, paths: Sequence[str], deadline: float) -> dict[str, bool]:
        """Whether the commit holds each path. Asks for no body, because most probed paths are
        candidates a batch only wants to rule out."""
        return self._read_chunks(repository, sha, paths, deadline, _EXISTS_SELECTION, lambda _path, entry: bool(entry))

    def _text(self, path: str, entry: dict[str, Any] | None) -> str:
        if entry is None:
            return _ABSENT
        text = entry.get("text")
        if not isinstance(text, str):
            # GitHub answers with no text for a binary or oversized blob, and an ownership file is
            # neither. Reading it as absent would reattribute everything under it to an ancestor.
            raise OwnershipUnavailable(f"{path} is not readable as text")
        if len(text.encode()) > _MAX_FILE_BYTES:
            raise OwnershipUnavailable(f"{path} exceeds the {_MAX_FILE_BYTES}-byte limit")
        return text

    def _read_chunks(
        self,
        repository: str,
        sha: str,
        paths: Sequence[str],
        deadline: float,
        selection: str,
        parse: "Callable[[str, dict[str, Any] | None], Any]",
    ) -> dict[str, Any]:
        def read_chunk(chunk: tuple[str, ...]) -> dict[str, Any]:
            query = _files_query(len(chunk), selection)
            variables = {f"p{index}": f"{sha}:{path}" for index, path in enumerate(chunk)}
            field = self._graphql(repository, query, variables, endpoint=_FILES_ENDPOINT)
            return {path: parse(path, _entry(field, index)) for index, path in enumerate(chunk)}

        results: dict[str, Any] = {}
        for chunk in _fetch_all(read_chunk, _chunks(list(dict.fromkeys(paths))), deadline).values():
            results.update(chunk)
        return results

    def _graphql(self, repository: str, query: str, variables: dict[str, str], *, endpoint: str) -> dict[str, Any]:
        """The ``repository`` object of one GraphQL answer.

        Anything else raises rather than reading as an empty repository, because a repository the
        credential cannot see answers the same way as one that declares nothing.
        """
        if not _is_safe_github_repo_path(repository):
            # A connected source's repository name is team-writable, so a crafted value must not
            # steer the query at a repository the caller did not name.
            raise OwnershipUnavailable(f"unsafe repository path: {repository!r}")
        owner, name = repository.split("/", 1)
        try:
            response = github_request(
                "POST",
                _GRAPHQL_URL,
                source=_EGRESS_SOURCE,
                headers={"Authorization": f"Bearer {self._token_value()}"},
                installation_id=self._installation_id,
                priority=self._priority,
                endpoint=endpoint,
                json={"query": query, "variables": {"owner": owner, "name": name, **variables}},
                timeout=_TIMEOUT_SECONDS,
                session=self._session,
            )
        except Exception as e:
            raise OwnershipUnavailable(f"could not read ownership files from {repository}: {e}") from e
        if response.status_code != HTTPStatus.OK:
            raise OwnershipUnavailable(f"{repository} answered {response.status_code} for {endpoint}")
        try:
            body = response.json()
        except ValueError as e:
            raise OwnershipUnavailable(f"{repository} answered with no JSON for {endpoint}") from e
        data = body.get("data") if isinstance(body, dict) else None
        field = data.get("repository") if isinstance(data, dict) else None
        if not isinstance(field, dict):
            raise OwnershipUnavailable(f"{repository} is unreadable for {endpoint}: {body.get('errors')}")
        return field

    def _token_value(self) -> str:
        # Once per batch: an integration mints or refreshes its token here, and a batch is far
        # shorter than a token's life.
        if self._resolved_token is None:
            self._resolved_token = self._token()
        return self._resolved_token


class AuthenticatedRepoFiles:
    """A repository's ownership files read with a credential, cached per commit.

    Build one per batch: it holds the batch's memo, its head commit, and its time budget.
    """

    def __init__(self, repository: str, fetcher: GitHubFilesFetcher) -> None:
        self.repository = repository
        self._fetcher = fetcher
        # Raw cache values, so ``_ABSENT`` rather than None for a file the commit does not hold.
        # The resolver reads each file again after the batch fetched it, and Redis is a network hop too.
        self._bodies: dict[str, str] = {}
        self._sha: str | None = None
        self._deadline = monotonic() + _RESOLVE_BUDGET_SECONDS

    def read(self, path: str) -> str | None:
        if path not in self._bodies:
            self.read_all([path])
        return None if self._bodies[path] == _ABSENT else self._bodies[path]

    def read_all(self, paths: list[str]) -> None:
        """Take every file the batch needs before it reads any, so one Redis round trip and one
        set of GraphQL calls cover them all."""
        todo = [path for path in paths if path not in self._bodies]
        self._bodies.update(self._batch("text", todo, self._fetcher.read_files))

    def exists_all(self, paths: list[str]) -> dict[str, bool]:
        return self._batch("exists", paths, self._fetcher.files_exist)

    def _batch(
        self,
        kind: str,
        paths: Iterable[str],
        fetch: "Callable[[str, str, Sequence[str], float], dict[str, Any]]",
    ) -> dict[str, Any]:
        todo = list(dict.fromkeys(paths))
        if not todo:
            return {}
        sha = self._head_commit_sha()
        by_key = {self._key(kind, sha, path): path for path in todo}
        known = {by_key[key]: value for key, value in cache.get_many(list(by_key)).items()}
        missing = [path for path in todo if path not in known]
        if missing:
            fetched = fetch(self.repository, sha, missing, self._deadline)
            cache.set_many(
                {self._key(kind, sha, path): value for path, value in fetched.items()}, _BLOB_CACHE_TTL_SECONDS
            )
            known.update(fetched)
        return known

    def _head_commit_sha(self) -> str:
        if self._sha is None:
            key = f"{_CACHE_PREFIX}:head:{self._fetcher.audience}:{self.repository}"
            cached = cache.get(key)
            if isinstance(cached, str) and cached:
                self._sha = cached
            else:
                self._sha = self._fetcher.head_commit_sha(self.repository)
                cache.set(key, self._sha, _HEAD_CACHE_TTL_SECONDS)
        return self._sha

    def _key(self, kind: str, sha: str, path: str) -> str:
        return f"{_CACHE_PREFIX}:{kind}:{self._fetcher.audience}:{self.repository}:{sha}:{path}"


def fetcher_for_team(team_id: int, repository: str, *, priority: Priority) -> RepoFiles:
    """The best reader the team has for this repository.

    A team whose GitHub App installation covers the repository reads it authenticated, which also
    works for a private repository. Every other team falls back to the anonymous raw host, which
    answers for a public repository only.
    """
    integration = GitHubIntegration.first_for_team_repository(
        team_id, repository, source=_EGRESS_SOURCE, priority=priority
    )
    if integration is None:
        return GitHubRepoFiles(repository)
    return AuthenticatedRepoFiles(repository, GitHubFilesFetcher.from_integration(integration, priority=priority))
