"""Set-level reads served from a result that was computed when the data changed.

The overview and the rankings cost the same for every person who opens the page, and their inputs
change a few times a day: a citation run, a reconcile, a sentiment pass, or an edit to the prompts or
the brands. Each of those writers calls `bump_data_version`, and a result is stored under the version
it was computed from, so a read after a write never gets a result from before it.

A writer that forgets to bump leaves a result in use until `RESULT_TTL_SECONDS` passes. The refresh
task recomputes the default views more often than that, so those stay current and are always stored.
"""

from __future__ import annotations

import uuid
import hashlib
from collections.abc import Callable
from typing import Any, TypeVar

from django.core.cache import cache
from django.db import transaction

from posthog.exceptions_capture import capture_exception
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.redis import get_client

RESULT_TTL_SECONDS = 30 * 60
# Outlives every result computed from it. A version that is gone reads as a new one, so nothing stale is served.
VERSION_TTL_SECONDS = 7 * 24 * 60 * 60

T = TypeVar("T")


def _version_key(team_id: int) -> str:
    return f"aeo_data_version:{team_id}"


def bump_data_version(team_id: int) -> None:
    """Call it after a write that changes what a set-level read returns. Inside a transaction, use
    `bump_data_version_on_commit`, or a read in between stores a result from before the write under
    the new version."""
    _bump(resolve_effective_team_id(team_id))


def bump_data_version_on_commit(team_id: int) -> None:
    """`bump_data_version` once the surrounding transaction commits, or at once outside a transaction."""
    # Resolved now: when a team is being deleted, its row is gone by the time the commit runs.
    canonical_team_id = resolve_effective_team_id(team_id)
    transaction.on_commit(lambda: _bump(canonical_team_id))


def _bump(canonical_team_id: int) -> None:
    try:
        get_client().set(_version_key(canonical_team_id), uuid.uuid4().hex, ex=VERSION_TTL_SECONDS)
    except Exception as error:
        # The write is already committed, so it must not fail on Redis. The result TTL bounds how
        # long the old result stays in use.
        capture_exception(error, {"team_id": canonical_team_id})


def _result_key(team_id: int, name: str, params: tuple[Any, ...]) -> str:
    # The version is read from the Redis primary. The cache may read a replica, which can still hold
    # the version from before a write that just committed.
    client = get_client()
    version = client.get(_version_key(team_id))
    if version is None:
        # nx keeps the version another request set in between.
        client.set(_version_key(team_id), uuid.uuid4().hex, ex=VERSION_TTL_SECONDS, nx=True)
        version = client.get(_version_key(team_id)) or uuid.uuid4().hex.encode()
    version = version.decode() if isinstance(version, bytes) else version
    # The parameters are strings, numbers, dates and None, so their repr is stable.
    digest = hashlib.sha256(repr(params).encode()).hexdigest()[:32]
    return f"aeo_result:{team_id}:{version}:{name}:{digest}"


def stored_result(
    team_id: int, name: str, params: tuple[Any, ...], compute: Callable[[], T], *, refresh: bool = False
) -> T:
    """The stored result of `compute` for these parameters at the current data version, computed and
    stored when there is none. `refresh` computes it again whatever is stored."""
    team_id = resolve_effective_team_id(team_id)
    # The key is read before the compute, so a write during the compute leaves the result under the
    # old version, where no later read looks.
    key = _result_key(team_id, name, params)
    if not refresh:
        stored = cache.get(key)
        if stored is not None:
            return stored
    result = compute()
    cache.set(key, result, RESULT_TTL_SECONDS)
    return result
