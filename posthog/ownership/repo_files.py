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
import structlog
from owners_yaml import BatchOwnershipSource
from requests.adapters import HTTPAdapter

from posthog.egress.github.transport import github_request
from posthog.models.integration.github import _is_safe_github_repo_path

logger = structlog.get_logger(__name__)

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


class ResponseTooLarge(OwnershipUnavailable):
    """A response body passed its byte limit. The same request gets the same body every time."""


class RepoFiles(BatchOwnershipSource, Protocol):
    """A repository's ownership files: one file, or a whole batch's before the resolver reads any."""


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
        # stop at the same deadline on their own, which the read in capped_text enforces.
        pool.shutdown(wait=False, cancel_futures=True)


def capped_text(response: requests.Response, *, description: str, limit: int, deadline: float | None = None) -> str:
    """A streamed response body as text, refused past ``limit`` bytes.

    The body belongs to the connected repository, so an unbounded read would put its bytes in a
    worker's memory and in Redis. ``description`` names what is being read, for the failure.
    """
    too_large = f"{description} exceeds the {limit}-byte limit"
    # Content-Length can be absent or wrong, so the streamed read below is the actual ceiling.
    declared = response.headers.get("Content-Length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise ResponseTooLarge(too_large)
    body = bytearray()
    for chunk in response.iter_content(chunk_size=8192):
        # The request timeout starts again on every chunk received, so a host that sends the body
        # slowly enough holds this read for as long as the byte limit allows. _fetch_all stops
        # waiting for a fetch at the deadline, so the fetch stops at the first chunk after it,
        # which the request timeout puts within _TIMEOUT_SECONDS of the deadline.
        if deadline is not None and monotonic() > deadline:
            raise OwnershipUnavailable(f"reading {description} passed the resolution budget")
        body.extend(chunk)
        if len(body) > limit:
            raise ResponseTooLarge(too_large)
    return body.decode(response.encoding or "utf-8", errors="replace")


def pooled_session(host: str) -> requests.Session:
    """A session whose connection pool is as wide as the fetch pool.

    requests pools ten connections by default and discards the overflow, so a smaller pool than the
    worker count makes most of a batch pay a fresh TLS handshake.
    """
    session = requests.Session()
    session.mount(host, HTTPAdapter(pool_connections=_FETCH_WORKERS, pool_maxsize=_FETCH_WORKERS))
    return session


def _cache_get_many(keys: list[str]) -> dict[str, Any]:
    """The cached values of ``keys``. An unreachable cache reads as all misses.

    The cache only saves requests. A Redis outage must not turn every ownership answer into an
    error page, because the files can still be read from GitHub.
    """
    try:
        return cache.get_many(keys)
    except Exception:
        logger.warning("ownership_cache_read_failed", exc_info=True)
        return {}


def _cached_by_path(path_by_key: dict[str, str]) -> dict[str, Any]:
    """The cached values of these keys, by the path each key stands for."""
    return {path_by_key[key]: value for key, value in _cache_get_many(list(path_by_key)).items()}


def _cache_set_many(values: dict[str, Any], ttl: int) -> None:
    try:
        cache.set_many(values, ttl)
    except Exception:
        logger.warning("ownership_cache_write_failed", exc_info=True)


class CachedRepoFiles:
    """The shared skeleton of a repository's file readers: one memo per batch, one Redis round trip
    per kind of read, and one time budget for the whole resolution.

    Build one per batch. A subclass says where a file comes from, how its cache key is built, and
    how long a cached value keeps.
    """

    def __init__(self, repository: str) -> None:
        self.repository = repository
        # Raw cache values, so ``_ABSENT`` rather than None for a file the repository does not hold.
        # The resolver reads each file again after the batch fetched it, and Redis is a network hop too.
        self._bodies: dict[str, str] = {}
        self._deadline = monotonic() + _RESOLVE_BUDGET_SECONDS

    def _cache_key(self, kind: str, path: str) -> str:
        raise NotImplementedError

    def _cache_ttl(self) -> int:
        raise NotImplementedError

    def _read_missing(self, paths: list[str]) -> dict[str, str]:
        raise NotImplementedError

    def _probe_missing(self, paths: list[str]) -> dict[str, bool]:
        raise NotImplementedError

    def _batch(self, kind: str, paths: Iterable[str], fetch: Callable[[list[str]], dict[str, _T]]) -> dict[str, _T]:
        todo = list(dict.fromkeys(paths))
        if not todo:
            return {}
        known = _cached_by_path({self._cache_key(kind, path): path for path in todo})
        missing = [path for path in todo if path not in known]
        if missing:
            fetched = fetch(missing)
            _cache_set_many({self._cache_key(kind, path): value for path, value in fetched.items()}, self._cache_ttl())
            known.update(fetched)
        return known

    def read(self, path: str) -> str | None:
        if path not in self._bodies:
            self.read_all([path])
        return None if self._bodies[path] == _ABSENT else self._bodies[path]

    def read_all(self, paths: list[str]) -> None:
        """Take every file the batch needs before it reads any, so one Redis round trip and one set
        of fetches cover them all."""
        self._bodies.update(self._batch("text", [p for p in paths if p not in self._bodies], self._read_missing))

    def exists_all(self, paths: list[str]) -> dict[str, bool]:
        return self._batch("exists", paths, self._probe_missing)


class GitHubRepoFiles(CachedRepoFiles):
    """A public repository's files over HTTPS, cached in Redis. Build one per batch: it holds the
    batch's memo and its HTTP connections."""

    def __init__(self, repository: str) -> None:
        super().__init__(repository)
        self._session = pooled_session(_RAW_HOST)

    def _cache_key(self, kind: str, path: str) -> str:
        return f"{_CACHE_PREFIX}:{kind}:{self.repository}:{_REF}:{path}"

    def _cache_ttl(self) -> int:
        return _CACHE_TTL_SECONDS + random.randint(0, _CACHE_TTL_JITTER_SECONDS)

    def _read_missing(self, paths: list[str]) -> dict[str, str]:
        return _fetch_all(self._get, paths, self._deadline)

    def _probe_missing(self, paths: list[str]) -> dict[str, bool]:
        return _fetch_all(self._head, paths, self._deadline)

    def _get(self, path: str) -> str:
        """The file's text, or ``_ABSENT`` when the repository has no such file."""
        with self._response("GET", path, stream=True) as response:
            if response.status_code == HTTPStatus.NOT_FOUND:
                return _ABSENT
            return capped_text(
                response,
                description=f"{path} in {self.repository}",
                limit=_MAX_FILE_BYTES,
                deadline=self._deadline,
            )

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
