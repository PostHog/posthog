"""A repository's ownership files, read over the network and cached.

The web container has no checkout, so the files are fetched from the repository's default branch.
A read that fails is fail-closed: the caller gets no attribution rather than a partial one.
"""

import random
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from time import monotonic
from typing import Any, Protocol, TypeVar

from django.core.cache import cache

import requests
from owners_yaml import OwnershipSource
from requests.adapters import HTTPAdapter

from posthog.egress.github.transport import github_request
from posthog.models.integration.github import _is_safe_github_repo_path

_T = TypeVar("_T")
_K = TypeVar("_K")

# The raw host serves a public repo's files off a CDN, so these reads draw on no GitHub API rate
# limit, and the HEAD ref follows the default branch. A private repo answers 404 to all of it, which
# the root-file guard in read_root catches.
_RAW_HOST = "https://raw.githubusercontent.com"
_REF = "HEAD"
_EGRESS_SOURCE = "engineering_analytics_ownership"
# Egress metrics are labeled by endpoint, so a raw file path per label would be unbounded.
_EGRESS_ENDPOINT = "/{owner}/{repo}/{ref}/{path}"
_TIMEOUT_SECONDS = 5.0
_FETCH_WORKERS = 16
# A connected repository controls these files, so an unbounded read would put its bytes in a
# worker's memory and in Redis. An ownership file is a few KB; this repo's whole set is under 25 KB.
_MAX_FILE_BYTES = 1024 * 1024
# The whole resolution, not one request. A quarantine snapshot is capped at HogQL's implicit 100
# rows, so a cold board can ask for hundreds of files; if the raw host stalls, the per-request
# timeout alone would still let one board load hold a web worker for minutes. Past this the board
# says ownership is unavailable, which beats hanging.
_RESOLVE_BUDGET_SECONDS = 20.0

# Ownership files change at review speed, so a stale answer stays right, and only the request that
# finds the cache cold pays for the fetches. A batch writes every key at once, so the jitter spreads
# their expiry over later requests instead of stranding one with the whole refetch.
_CACHE_TTL_SECONDS = 6 * 60 * 60
_CACHE_TTL_JITTER_SECONDS = 60 * 60
_CACHE_PREFIX = "eng_analytics:repo_file"
# Absence needs a cache value of its own, and no file holds this one.
_ABSENT = "\x00absent"

ROOT_OWNERS_FILE = "owners.yaml"


class OwnershipUnavailable(Exception):
    """The repository's ownership files could not be read, so no attribution is trustworthy."""


class NoRootOwnersFile(OwnershipUnavailable):
    """The repository answers with no root owners file, which is normal for most repositories."""


class RepoFiles(OwnershipSource, Protocol):
    """An ownership source that also answers which paths the repository holds, in batches."""

    def exists_all(self, paths: list[str]) -> dict[str, bool]: ...

    def read_all(self, paths: list[str]) -> None: ...


def _ttl() -> int:
    return _CACHE_TTL_SECONDS + random.randint(0, _CACHE_TTL_JITTER_SECONDS)


def _fetch_all(fetch: Callable[[_K], _T], keys: Iterable[_K], deadline: float) -> dict[_K, _T]:
    """Fetch every distinct key concurrently, within what is left of the batch's budget. The one
    place this package waits on the network. A key is one file for the raw host, and one chunk of
    files for the GraphQL reader."""
    todo = list(dict.fromkeys(keys))
    if not todo:
        return {}
    pool = ThreadPoolExecutor(max_workers=min(_FETCH_WORKERS, len(todo)))
    try:
        futures = {key: pool.submit(fetch, key) for key in todo}
        return {key: future.result(max(deadline - monotonic(), 0)) for key, future in futures.items()}
    except TimeoutError as e:
        raise OwnershipUnavailable(f"ownership took longer than {_RESOLVE_BUDGET_SECONDS}s") from e
    finally:
        # Not a `with` block: its exit waits for every running fetch, which holds the request thread
        # past the deadline. A lost batch drops the queued fetches and leaves the running ones to
        # stop at the same deadline on their own, which the read in _capped_text enforces.
        pool.shutdown(wait=False, cancel_futures=True)


class GitHubRepoFiles:
    """A public repository's files over HTTPS, cached in Redis. Build one per batch: it holds the
    batch's memo and its HTTP connections."""

    def __init__(self, repository: str) -> None:
        self.repository = repository
        # Raw cache values, so ``_ABSENT`` rather than None for a file the repository does not hold.
        # The resolver reads each file again after the batch fetched it, and Redis is a network hop too.
        self._bodies: dict[str, str] = {}
        self._session = requests.Session()
        # requests pools 10 connections by default and discards the overflow, so a smaller pool than
        # the worker count makes most of the batch pay a fresh TLS handshake.
        self._session.mount(_RAW_HOST, HTTPAdapter(pool_connections=_FETCH_WORKERS, pool_maxsize=_FETCH_WORKERS))
        self._deadline = monotonic() + _RESOLVE_BUDGET_SECONDS

    def read(self, path: str) -> str | None:
        if path not in self._bodies:
            self.read_all([path])
        return None if self._bodies[path] == _ABSENT else self._bodies[path]

    def read_all(self, paths: list[str]) -> None:
        """Take every file the batch needs before it reads any, so one Redis round trip and one
        concurrent fetch cover them all."""
        self._bodies.update(self._batch("text", [p for p in paths if p not in self._bodies], self._get))

    def exists_all(self, paths: list[str]) -> dict[str, bool]:
        return self._batch("exists", paths, self._head)

    def _batch(self, kind: str, paths: Iterable[str], fetch: Callable[[str], _T]) -> dict[str, _T]:
        todo = list(dict.fromkeys(paths))
        if not todo:
            return {}
        by_key = {self._key(kind, path): path for path in todo}
        known = {by_key[key]: value for key, value in cache.get_many(list(by_key)).items()}
        fetched = _fetch_all(fetch, [path for path in todo if path not in known], self._deadline)
        if fetched:
            cache.set_many({self._key(kind, path): value for path, value in fetched.items()}, _ttl())
            known.update(fetched)
        return known

    def _key(self, kind: str, path: str) -> str:
        return f"{_CACHE_PREFIX}:{kind}:{self.repository}:{_REF}:{path}"

    def _get(self, path: str) -> str:
        """The file's text, or ``_ABSENT`` when the repository has no such file."""
        with self._response("GET", path, stream=True) as response:
            if response.status_code == HTTPStatus.NOT_FOUND:
                return _ABSENT
            return self._capped_text(response, path)

    def _head(self, path: str) -> bool:
        with self._response("HEAD", path) as response:
            return response.status_code != HTTPStatus.NOT_FOUND

    def _response(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        """Any status but 200 or 404 raises rather than reading as absent, because a missing
        ownership file silently reattributes everything under it to an ancestor."""
        if not _is_safe_github_repo_path(self.repository):
            # Source config is team-writable, so a crafted value must not steer the URL.
            raise OwnershipUnavailable(f"unsafe repository path: {self.repository!r}")
        url = f"{_RAW_HOST}/{self.repository}/{_REF}/{path}"
        try:
            response = github_request(
                method,
                url,
                source=_EGRESS_SOURCE,
                endpoint=_EGRESS_ENDPOINT,
                timeout=_TIMEOUT_SECONDS,
                session=self._session,
                **kwargs,
            )
        except Exception as e:
            raise OwnershipUnavailable(f"could not read {path} from {self.repository}: {e}") from e
        if response.status_code not in (HTTPStatus.OK, HTTPStatus.NOT_FOUND):
            raise OwnershipUnavailable(f"{self.repository} answered {response.status_code} for {path}")
        return response

    def _capped_text(self, response: requests.Response, path: str) -> str:
        too_large = f"{path} in {self.repository} exceeds the {_MAX_FILE_BYTES}-byte limit"
        # Content-Length can be absent or wrong, so the streamed read below is the actual ceiling.
        declared = response.headers.get("Content-Length")
        if declared is not None and declared.isdigit() and int(declared) > _MAX_FILE_BYTES:
            raise OwnershipUnavailable(too_large)
        body = bytearray()
        for chunk in response.iter_content(chunk_size=8192):
            # The request timeout starts again on every chunk received, so a host that sends the body
            # slowly enough holds this read for as long as the byte limit allows. _fetch_all stops
            # waiting for a fetch at the deadline, so the fetch stops at the first chunk after it,
            # which the request timeout puts within _TIMEOUT_SECONDS of the deadline.
            if monotonic() > self._deadline:
                raise OwnershipUnavailable(f"reading {path} from {self.repository} passed the resolution budget")
            body.extend(chunk)
            if len(body) > _MAX_FILE_BYTES:
                raise OwnershipUnavailable(too_large)
        return body.decode(response.encoding or "utf-8", errors="replace")
