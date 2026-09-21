"""A repository's ownership files read from the GitHub API with a credential.

The raw host in ``repo_files`` serves public repositories only, and it costs one request per file.
This module reads the same files through the GitHub GraphQL API, which authenticates, answers for a
private repository, and returns about a hundred files per request.

Every read is pinned to the default branch's head commit. The content at a commit never changes, so
the cache can hold it for days, and a merge is visible as soon as the short-lived head lookup
expires. The raw host cannot name a commit, so it keeps its own cache and its own six-hour staleness
window.
"""

import json
from collections.abc import Callable, Sequence
from functools import partial
from http import HTTPStatus
from typing import Any

from django.core.cache import cache

import requests
import structlog

from posthog.egress.github.transport import GitHubRateLimitError, github_request, raise_if_github_rate_limited
from posthog.egress.limiter.policies import Priority
from posthog.egress.observability.observability import scope_fingerprint
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.integration.github import _is_safe_github_repo_path
from posthog.ownership.repo_files import (
    _ABSENT,
    _MAX_FILE_BYTES,
    CachedRepoFiles,
    GitHubRepoFiles,
    OwnershipUnavailable,
    _fetch_all,
    capped_text,
    pooled_session,
)

logger = structlog.get_logger(__name__)

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
# Which integration covers a repository costs one uncached GitHub probe per integration the team
# has, and a page load asks for it on every request. Short for the same reason as the head lookup:
# a repository added to an installation has to become readable without anyone clearing a cache.
_INTEGRATION_CACHE_TTL_SECONDS = 120
# No integration covers the repository. A row id is never 0, so the negative needs no second key.
_NO_COVERING_INTEGRATION = 0
# One answer carries up to _CHUNK_FILES blobs, and the per-file limit alone would let a chunk of
# near-limit files materialize a hundred megabytes in a worker and in the cache. A real ownership
# file is a few kilobytes, so a whole chunk of them is tens of kilobytes; this leaves that room many
# times over and still bounds what one answer can cost.
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024

_HEAD_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { oid } }
  }
}
"""

# Each file is one aliased `object` lookup. The path rides in a variable rather than in the query
# text, so a path can never change the shape of the query. `isTruncated` comes along because GitHub
# cuts a large blob's `text` short without saying so anywhere else in the answer.
_TEXT_SELECTION = "... on Blob { text isTruncated }"
_EXISTS_SELECTION = "__typename"


def _token_audience(token: str) -> str:
    """A stable name for what one token is allowed to read.

    Two credentials must never share cached file content: a private repository one installation can
    read is not readable by the next caller that names the same repository. The token itself must
    stay out of the key, so the key carries the same digest the egress metrics use for an identity
    that cannot appear in plain form.
    """
    return f"token:{scope_fingerprint(token)}"


def _files_query(count: int, selection: str) -> str:
    variables = ", ".join(f"$p{index}: String!" for index in range(count))
    fields = "\n".join(f"    f{index}: object(expression: $p{index}) {{ {selection} }}" for index in range(count))
    return f"query($owner: String!, $name: String!, {variables}) {{\n  repository(owner: $owner, name: $name) {{\n{fields}\n  }}\n}}"


def _chunks(paths: Sequence[str]) -> list[tuple[str, ...]]:
    return [tuple(paths[start : start + _CHUNK_FILES]) for start in range(0, len(paths), _CHUNK_FILES)]


def _entry(field: dict[str, Any], index: int) -> dict[str, Any] | None:
    entry = field.get(f"f{index}")
    return entry if isinstance(entry, dict) else None


def _refreshed_installation_token(integration: GitHubIntegrationBase) -> str:
    """A newly minted installation token.

    ``get_access_token`` returns the stored token until it is close to expiry, so it can hand back
    the very token a 401 has just refused. Only ``refresh_access_token`` mints a new one.
    """
    integration.refresh_access_token()
    return integration.get_access_token()


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
            refresh=partial(_refreshed_installation_token, integration),
            installation_id=installation_id,
            audience=(
                f"installation:{installation_id}"
                if installation_id
                else f"integration:{type(integration.integration).__name__}:{integration.integration.pk}"
            ),
            priority=priority,
        )

    @classmethod
    def from_token(
        cls,
        token: str,
        *,
        installation_id: str | None = None,
        refresh: Callable[[], str] | None = None,
        priority: Priority,
    ) -> "GitHubFilesFetcher":
        """Read with a token the caller already holds: a personal access token, or an installation
        token minted by a product's own GitHub App. Pass ``installation_id`` when the token belongs
        to an installation, so the calls are gated on that installation's shared budget.

        ``refresh`` mints a replacement after a 401, for a caller that can mint one. A personal
        access token cannot be re-minted, so it leaves ``refresh`` unset and fails closed instead."""
        return cls(
            token=lambda: token,
            refresh=refresh,
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
        refresh: Callable[[], str] | None = None,
    ) -> None:
        self.audience = audience
        self._token = token
        self._refresh = refresh
        self._resolved_token: str | None = None
        self._installation_id = installation_id
        self._priority = priority
        self._session = pooled_session(_API_HOST)

    def head_commit_sha(self, repository: str) -> str | None:
        """The commit at the head of the repository's default branch, or None when there is none.

        A repository with no commits has no default branch, and GitHub answers that with a null
        ``defaultBranchRef`` and no error. It holds no file, so that is a normal answer rather than
        an unreadable one: a caller that fails it instead would take down every repository it reads
        beside this one.
        """
        field = self._graphql(repository, _HEAD_QUERY, {}, endpoint=_HEAD_ENDPOINT)
        ref = field.get("defaultBranchRef")
        if ref is None:
            return None
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
        if entry.get("isTruncated"):
            # GitHub cuts a large blob's text short and still answers 200. Parsing the prefix would
            # read as a complete file and cache a wrong ownership answer for a week.
            raise OwnershipUnavailable(f"{path} came back truncated")
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
            field = self._graphql(repository, query, variables, endpoint=_FILES_ENDPOINT, deadline=deadline)
            return {path: parse(path, _entry(field, index)) for index, path in enumerate(chunk)}

        results: dict[str, Any] = {}
        for chunk in _fetch_all(read_chunk, _chunks(list(dict.fromkeys(paths))), deadline).values():
            results.update(chunk)
        return results

    def _graphql(
        self,
        repository: str,
        query: str,
        variables: dict[str, str],
        *,
        endpoint: str,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        """The ``repository`` object of one GraphQL answer.

        Anything else raises rather than reading as an empty repository, because a repository the
        credential cannot see answers the same way as one that declares nothing.
        """
        if not _is_safe_github_repo_path(repository):
            # A connected source's repository name is team-writable, so a crafted value must not
            # steer the query at a repository the caller did not name.
            raise OwnershipUnavailable(f"unsafe repository path: {repository!r}")
        owner, name = repository.split("/", 1)
        payload = {"query": query, "variables": {"owner": owner, "name": name, **variables}}
        status, body = self._answer(repository, payload, endpoint=endpoint, deadline=deadline)
        if status == HTTPStatus.UNAUTHORIZED and self._refresh is not None:
            # The token was revoked or rotated under the batch, and it stays memoized, so every
            # later read would fail with it too. A 401 means nothing ran, so the retry is safe.
            self._refresh_token(repository)
            status, body = self._answer(repository, payload, endpoint=endpoint, deadline=deadline)
        if status != HTTPStatus.OK:
            raise OwnershipUnavailable(f"{repository} answered {status} for {endpoint}")
        errors = body.get("errors") if isinstance(body, dict) else None
        if errors:
            # GitHub reports a path the commit does not hold as a null alias and no error at all, so
            # an error means the alias failed rather than being absent. A partial answer also carries
            # the repository object, and reading its null aliases as absent files would cache that
            # absence for days and move ownership to an ancestor.
            raise OwnershipUnavailable(f"{repository} answered with errors for {endpoint}: {errors}")
        data = body.get("data") if isinstance(body, dict) else None
        field = data.get("repository") if isinstance(data, dict) else None
        if not isinstance(field, dict):
            raise OwnershipUnavailable(f"{repository} is unreadable for {endpoint}")
        return field

    def _answer(
        self, repository: str, payload: dict[str, Any], *, endpoint: str, deadline: float | None
    ) -> tuple[int, Any]:
        """One POST's status and decoded body, read under the response cap and closed before it
        returns."""
        with self._post(repository, payload, endpoint=endpoint) as response:
            if response.status_code != HTTPStatus.OK:
                return response.status_code, None
            text = capped_text(
                response,
                description=f"the {endpoint} answer for {repository}",
                limit=_MAX_RESPONSE_BYTES,
                deadline=deadline,
            )
        try:
            return HTTPStatus.OK, json.loads(text)
        except ValueError as e:
            raise OwnershipUnavailable(f"{repository} answered with no JSON for {endpoint}") from e

    def _post(self, repository: str, payload: dict[str, Any], *, endpoint: str) -> requests.Response:
        try:
            response = github_request(
                "POST",
                _GRAPHQL_URL,
                source=_EGRESS_SOURCE,
                headers={"Authorization": f"Bearer {self._token_value()}"},
                installation_id=self._installation_id,
                priority=self._priority,
                endpoint=endpoint,
                json=payload,
                timeout=_TIMEOUT_SECONDS,
                session=self._session,
                # The body is read under a cap in _answer, so it must not be buffered whole first.
                stream=True,
            )
            # A rate limit answers 403 or 429, which would otherwise read as a plain refusal. It is
            # still fail-closed, but the failure says which of the two it was.
            raise_if_github_rate_limited(response)
        except Exception as e:
            raise OwnershipUnavailable(f"could not read ownership files from {repository}: {e}") from e
        return response

    def _refresh_token(self, repository: str) -> None:
        if self._refresh is None:
            return
        try:
            self._resolved_token = self._refresh()
        except Exception as e:
            raise OwnershipUnavailable(f"could not refresh the credential for {repository}: {e}") from e

    def _token_value(self) -> str:
        # Once per batch: an integration mints or refreshes its token here, and a batch is far
        # shorter than a token's life.
        if self._resolved_token is None:
            self._resolved_token = self._token()
        return self._resolved_token


class AuthenticatedRepoFiles(CachedRepoFiles):
    """A repository's ownership files read with a credential, cached per commit.

    Build one per batch: it holds the batch's memo, its head commit, and its time budget.

    ``fresh_head`` asks GitHub for the head on this run rather than reading the shared head cache,
    for a caller that derives a decision it never stores and so cannot correct later. It still
    writes the head cache, and blob reads stay cached because content at a commit never changes.
    """

    def __init__(self, repository: str, fetcher: GitHubFilesFetcher, *, fresh_head: bool = False) -> None:
        super().__init__(repository)
        self._fetcher = fetcher
        self._fresh_head = fresh_head
        self._sha: str | None = None

    def _head_commit_sha(self) -> str | None:
        if self._sha is None:
            key = f"{_CACHE_PREFIX}:head:{self._fetcher.audience}:{self.repository}"
            cached = None if self._fresh_head else cache.get(key)
            if isinstance(cached, str) and cached:
                self._sha = cached
            else:
                self._sha = self._fetcher.head_commit_sha(self.repository)
                if self._sha is not None:
                    cache.set(key, self._sha, _HEAD_CACHE_TTL_SECONDS)
        return self._sha

    def _commit(self) -> str:
        sha = self._head_commit_sha()
        if sha is None:
            raise OwnershipUnavailable(f"{self.repository} has no commits")
        return sha

    def _cache_key(self, kind: str, path: str) -> str:
        return f"{_CACHE_PREFIX}:{kind}:{self._fetcher.audience}:{self.repository}:{self._commit()}:{path}"

    def _cache_ttl(self) -> int:
        return _BLOB_CACHE_TTL_SECONDS

    def _read_missing(self, paths: list[str]) -> dict[str, str]:
        return self._fetcher.read_files(self.repository, self._commit(), paths, self._deadline)

    def _probe_missing(self, paths: list[str]) -> dict[str, bool]:
        return self._fetcher.files_exist(self.repository, self._commit(), paths, self._deadline)

    def read_all(self, paths: list[str]) -> None:
        if self._head_commit_sha() is None:
            # A repository with no commits holds no file. There is no commit to key a cache entry
            # by, so the absence is answered per batch rather than written for a week.
            self._bodies.update({path: _ABSENT for path in paths if path not in self._bodies})
            return
        super().read_all(paths)

    def exists_all(self, paths: list[str]) -> dict[str, bool]:
        if self._head_commit_sha() is None:
            return dict.fromkeys(paths, False)
        return super().exists_all(paths)


def _covering_integration(team_id: int, repository: str, *, priority: Priority) -> GitHubIntegration | None:
    """The team's GitHub integration whose installation can read the repository.

    The lookup itself probes GitHub once per integration the team has, uncached, and a page load
    asks for it on every request. Only the decision is cached, never a token: the id of the
    integration that answered, or the marker for "none of them did", so a team with no installation
    does not re-probe either.
    """
    key = f"{_CACHE_PREFIX}:integration:{team_id}:{repository.casefold()}"
    cached = cache.get(key)
    if isinstance(cached, int):
        if cached == _NO_COVERING_INTEGRATION:
            return None
        integration = Integration.objects.filter(team_id=team_id, id=cached, kind="github").first()
        # A disconnected integration falls through to a fresh lookup rather than to no reader.
        if integration is not None:
            return GitHubIntegration(integration, source=_EGRESS_SOURCE, priority=priority)
    covering = GitHubIntegration.first_for_team_repository(
        team_id, repository, source=_EGRESS_SOURCE, priority=priority
    )
    decision = covering.integration.pk if covering is not None else _NO_COVERING_INTEGRATION
    cache.set(key, decision, _INTEGRATION_CACHE_TTL_SECONDS)
    return covering


def fetcher_for_team(
    team_id: int, repository: str, *, priority: Priority
) -> "AuthenticatedRepoFiles | GitHubRepoFiles":
    """The best reader the team has for this repository.

    A team whose GitHub App installation covers the repository reads it authenticated, which also
    works for a private repository. Every other team falls back to the anonymous raw host, which
    answers for a public repository only.
    """
    try:
        integration = _covering_integration(team_id, repository, priority=priority)
    except (EgressBudgetExhausted, GitHubRateLimitError):
        # The probe is optional enrichment for a caller that already handles an unresolved answer,
        # so a spent budget must degrade rather than raise past it. Nothing is cached: the next
        # call has to probe again once the budget refills.
        logger.warning("ownership_covering_integration_budget_exhausted", team_id=team_id, repository=repository)
        return GitHubRepoFiles(repository)
    if integration is None:
        return GitHubRepoFiles(repository)
    return AuthenticatedRepoFiles(repository, GitHubFilesFetcher.from_integration(integration, priority=priority))
