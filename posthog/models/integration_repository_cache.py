"""Per-repository heavy cache for GitHub integrations.

Stores README + full file tree + descriptive metadata so the Signals selection
agent can server-side grep paths via HogQL (`ARRAY JOIN splitByString('\\n',
tree_paths)`) instead of hitting GitHub's `/search/code` endpoint (30 req/min
ceiling). The lightweight (id, name, full_name) list stays on
``Integration.repository_cache`` (JSONField) — that read path stays cheap for
the IDE repo dropdown.
"""

from __future__ import annotations

import time
import uuid
import base64
import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta
from typing import TYPE_CHECKING
from urllib.parse import quote

from django.db import models
from django.utils import timezone

import structlog
import temporalio.activity

from posthog import redis as posthog_redis
from posthog.helpers.async_concurrency import run_parallel_with_backoff
from posthog.models.integration import GitHubIntegration, GitHubIntegrationError, Integration
from posthog.models.utils import UUIDModel
from posthog.sync import database_sync_to_async

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)

# Rows fresher than this skip GitHub entirely. Mirrors
# GITHUB_REPOSITORY_CACHE_TTL_SECONDS semantics (see `Integration.repository_cache`).
# Past the TTL we still do a cheap SHA check before deciding to refetch the tree.
GITHUB_REPOSITORY_FULL_CACHE_TTL_SECONDS = 60 * 60

# Single-flight lock for `sync_full_cache`. First caller (leader) acquires the lock and runs;
# concurrent callers (followers) poll until released, then read the warm cache and effectively no-op.
SYNC_LOCK_KEY_PREFIX = "github_full_cache_sync"
SYNC_LOCK_TTL_SECONDS = 60 * 15
SYNC_LOCK_HEARTBEAT_INTERVAL_SECONDS = 60
SYNC_LOCK_POLL_INTERVAL_SECONDS = 1
# Hard cap on follower wait. While the lock key exists, the leader heartbeated within the last
# TTL window, so we wait; if the leader crashes, the TTL expires and the next acquire promotes us.
SYNC_LOCK_MAX_WAIT_SECONDS = 60 * 20

# Token-checked release: only delete the key if we still hold the token. Safe even if the TTL already expired.
_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""
# Token-checked extend: leader heartbeat refreshes its own TTL only — won't touch a successor's lock.
_EXTEND_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("expire", KEYS[1], ARGV[2])
end
return 0
"""


class SyncFullCacheTimeoutError(Exception):
    """Raised when a follower exceeds SYNC_LOCK_MAX_WAIT_SECONDS waiting for the leader."""


class IntegrationRepositoryCacheEntry(UUIDModel):
    integration = models.ForeignKey(Integration, on_delete=models.CASCADE, related_name="repository_cache_entries")
    # Denormalized from Integration so HogQL's team_id guard can filter this table directly.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    full_name = models.TextField()  # Duplicate field, required for indexing
    description = models.TextField(null=True, blank=True)
    topics = models.JSONField(default=list, blank=True)
    archived = models.BooleanField(default=False)
    fork = models.BooleanField(default=False)
    primary_language = models.TextField(null=True, blank=True)
    default_branch = models.TextField()
    default_branch_sha = models.TextField()
    readme = models.TextField(default="", blank=True)
    # Newline-separated blob paths. Server-side grep uses HogQL
    # `ARRAY JOIN splitByString('\n', tree_paths) AS path` to unnest and ILIKE on path.
    tree_paths = models.TextField(default="", blank=True)
    # TODO: when `tree_truncated=True` the path set is incomplete (~50k+ entry repos).
    # Affects <2% of repos, skews to monorepos. Future fix: paginated recursive subtree fetch.
    tree_truncated = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "posthog"
        unique_together = [("integration", "full_name")]
        # `unique_together` already creates a btree index on (integration, full_name) — no need to duplicate it.
        indexes = [
            models.Index(fields=["team", "updated_at"]),
        ]


class GitHubRepositoryFullCache:
    """Owns the heavy per-repo cache (README + tree + metadata) for a GitHub integration."""

    def __init__(self, github: GitHubIntegration) -> None:
        self.github = github

    @property
    def integration(self) -> Integration:
        return self.github.integration

    @staticmethod
    def _is_fresh(entry: IntegrationRepositoryCacheEntry) -> bool:
        age = timezone.now() - entry.updated_at
        return age < timedelta(seconds=GITHUB_REPOSITORY_FULL_CACHE_TTL_SECONDS)

    def _get_existing_entry(self, full_name: str) -> IntegrationRepositoryCacheEntry | None:
        # Defer the heavy blob columns: the freshness/SHA decision and light-path metadata save
        # never read them, and bulk sync would otherwise drag MBs of `tree_paths` per repo through
        # Postgres just to decide the cache is still good.
        return (
            self.integration.repository_cache_entries.filter(full_name=full_name).defer("readme", "tree_paths").first()
        )

    def _fetch_repo_meta(self, owner: str, repo: str, full_name: str) -> tuple[dict, str, str]:
        """Pure-network: repo metadata + default-branch SHA. No DB I/O when token is fresh."""
        repo_data = self.github._gh_api_get(f"/repos/{owner}/{repo}", endpoint="/repos/{owner}/{repo}")
        default_branch = repo_data.get("default_branch") or "main"
        # Quote the ref so branches like `release/1.0` hit the right endpoint (precedent: products/visual_review/backend/logic.py).
        branch_data = self.github._gh_api_get(
            f"/repos/{owner}/{repo}/branches/{quote(default_branch, safe='')}",
            endpoint="/repos/{owner}/{repo}/branches/{branch}",
        )
        commit = branch_data.get("commit") or {}
        default_branch_sha = commit.get("sha")
        if not isinstance(default_branch_sha, str) or not default_branch_sha:
            raise GitHubIntegrationError(
                f"GitHubRepositoryFullCache: branch {default_branch} missing commit sha for {full_name}"
            )
        return repo_data, default_branch, default_branch_sha

    def _save_light(self, existing: IntegrationRepositoryCacheEntry, repo_data: dict, default_branch: str) -> None:
        existing.description = repo_data.get("description")
        existing.topics = repo_data.get("topics") or []
        existing.archived = bool(repo_data.get("archived", False))
        existing.fork = bool(repo_data.get("fork", False))
        existing.primary_language = repo_data.get("language")
        existing.default_branch = default_branch
        existing.save(
            update_fields=[
                "description",
                "topics",
                "archived",
                "fork",
                "primary_language",
                "default_branch",
                "updated_at",
            ]
        )

    def _fetch_heavy(self, owner: str, repo: str, default_branch_sha: str) -> tuple[str, str, bool]:
        """Pure-network: README + recursive tree pinned to ``default_branch_sha``."""
        # Best-effort README (404 is normal — repos without one stay with empty string).
        readme_text = ""
        try:
            # Pinned to default_branch_sha so README, tree_paths, and SHA all describe the same commit.
            readme_data = self.github._gh_api_get(
                f"/repos/{owner}/{repo}/readme?ref={default_branch_sha}",
                endpoint="/repos/{owner}/{repo}/readme",
            )
            encoded = readme_data.get("content")
            if isinstance(encoded, str):
                readme_text = base64.b64decode(encoded).decode("utf-8", errors="replace")
        except GitHubIntegrationError as exc:
            if getattr(exc, "status_code", None) != 404:
                # Rate-limit and other retryable errors propagate so run_parallel_with_backoff can retry.
                raise
        # Recursive file tree → newline-separated blob paths for ARRAY JOIN grep.
        tree_data = self.github._gh_api_get(
            f"/repos/{owner}/{repo}/git/trees/{default_branch_sha}?recursive=1",
            endpoint="/repos/{owner}/{repo}/git/trees/{sha}",
        )
        tree_entries = tree_data.get("tree") or []
        tree_paths = "\n".join(
            entry["path"]
            for entry in tree_entries
            if isinstance(entry, dict) and entry.get("type") == "blob" and isinstance(entry.get("path"), str)
        )
        return readme_text, tree_paths, bool(tree_data.get("truncated", False))

    def _upsert_heavy(
        self,
        *,
        full_name: str,
        repo_data: dict,
        default_branch: str,
        default_branch_sha: str,
        readme_text: str,
        tree_paths: str,
        tree_truncated: bool,
    ) -> IntegrationRepositoryCacheEntry:
        entry, _ = IntegrationRepositoryCacheEntry.objects.update_or_create(
            integration=self.integration,
            full_name=full_name,
            defaults={
                "team_id": self.integration.team_id,
                "description": repo_data.get("description"),
                "topics": repo_data.get("topics") or [],
                "archived": bool(repo_data.get("archived", False)),
                "fork": bool(repo_data.get("fork", False)),
                "primary_language": repo_data.get("language"),
                "default_branch": default_branch,
                "default_branch_sha": default_branch_sha,
                "readme": readme_text,
                "tree_paths": tree_paths,
                "tree_truncated": tree_truncated,
            },
        )
        return entry

    async def sync_full_cache_entry_async(
        self, full_name: str, *, path_log: list[str] | None = None
    ) -> IntegrationRepositoryCacheEntry:
        """Fetch one repo's heavy metadata + README + file tree, upsert the cache row, without blocking DB"""
        # 1. Validate input.
        if "/" not in full_name:
            raise ValueError(f"full_name must be in 'owner/repo' format, got {full_name!r}")
        full_name = full_name.lower()
        owner, repo = full_name.split("/", 1)

        # 2. DB: TTL gate.
        existing = await database_sync_to_async(self._get_existing_entry)(full_name)
        if existing and existing.default_branch_sha and self._is_fresh(existing):
            if path_log is not None:
                path_log.append("ttl_hit")
            return existing

        # 3. Network: repo metadata + branch SHA.
        repo_data, default_branch, default_branch_sha = await asyncio.to_thread(
            self._fetch_repo_meta, owner, repo, full_name
        )

        # 4. DB: light path if SHA unchanged.
        if existing and existing.default_branch_sha == default_branch_sha:
            await database_sync_to_async(self._save_light)(existing, repo_data, default_branch)
            if path_log is not None:
                path_log.append("sha_unchanged")
            return existing

        # 5. Network: heavy fetch.
        readme_text, tree_paths, tree_truncated = await asyncio.to_thread(
            self._fetch_heavy, owner, repo, default_branch_sha
        )

        # 6. DB: upsert.
        entry = await database_sync_to_async(self._upsert_heavy)(
            full_name=full_name,
            repo_data=repo_data,
            default_branch=default_branch,
            default_branch_sha=default_branch_sha,
            readme_text=readme_text,
            tree_paths=tree_paths,
            tree_truncated=tree_truncated,
        )
        if path_log is not None:
            path_log.append("heavy")
        return entry

    @database_sync_to_async
    def _evict_orphans(self, valid_full_names: set[str]) -> int:
        deleted, _ = self.integration.repository_cache_entries.exclude(full_name__in=valid_full_names).delete()
        return deleted

    async def sync_full_cache(self, *, concurrency: int = 10) -> list[IntegrationRepositoryCacheEntry | BaseException]:
        """Bulk heavy sync for all repos this integration sees.

        Single-flighted per-integration via Redis: concurrent callers wait on the leader and then
        read the warm cache (each entry's TTL fast path makes their re-sync effectively a no-op).

        The light JSONField cache (``Integration.repository_cache``) is the authoritative
        set — rows for repos no longer in it are deleted before syncing.
        """
        async with _acquire_sync_lock(self.integration.id):
            return await self._sync_full_cache_locked(concurrency=concurrency)

    async def _sync_full_cache_locked(
        self, *, concurrency: int
    ) -> list[IntegrationRepositoryCacheEntry | BaseException]:
        # 1. Source of truth: the light cache. This also refreshes it from GitHub if >1h stale.
        repos = await self.github.list_all_cached_repositories_async()
        valid_full_names = {r["full_name"].lower() for r in repos if isinstance(r.get("full_name"), str)}
        # 2. Evict orphans — heavy cache is always a subset of the light cache.
        evicted = await self._evict_orphans(valid_full_names)
        if evicted:
            logger.info(
                "github_full_cache.evicted_orphans",
                integration_id=self.integration.id,
                count=evicted,
            )
        if not valid_full_names:
            return []

        # Refresh the token now, before starting the parallel workers below. Otherwise
        # they would each try to refresh it at the same time, causing duplicate API calls.
        await database_sync_to_async(self.github.get_access_token)()

        # `path_log` collects which branch each parallel call took
        path_log: list[str] = []

        def make_fn(full_name: str) -> Callable[[], Awaitable[IntegrationRepositoryCacheEntry]]:
            async def run() -> IntegrationRepositoryCacheEntry:
                return await self.sync_full_cache_entry_async(full_name, path_log=path_log)

            return run

        # 3. Sync each remaining repo with bounded concurrency + rate-limit-aware backoff.
        start = time.monotonic()
        results = await run_parallel_with_backoff(
            [make_fn(name) for name in valid_full_names],
            concurrency=concurrency,
            is_retryable=lambda exc: isinstance(exc, GitHubIntegrationError) and exc.is_rate_limit,
            get_retry_delay=lambda exc: getattr(exc, "retry_after_seconds", None),
        )
        # 4. Single summary line — distinguishes "warm cache, all hits" from "did real work".
        errors = sum(1 for r in results if isinstance(r, BaseException))
        logger.info(
            "github_full_cache.sync_full_cache",
            integration_id=self.integration.id,
            total=len(results),
            ttl_hits=path_log.count("ttl_hit"),
            sha_unchanged=path_log.count("sha_unchanged"),
            heavy=path_log.count("heavy"),
            errors=errors,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return results


@contextlib.asynccontextmanager
async def _acquire_sync_lock(integration_id: int) -> AsyncIterator[None]:
    """Single-flight lock for `sync_full_cache`. Leader runs; followers poll until release/expiry."""
    redis = posthog_redis.get_async_client()
    lock_key = f"{SYNC_LOCK_KEY_PREFIX}:{integration_id}"
    lock_token = uuid.uuid4().hex

    # Wait for leadership (or the existing leader to finish). Each failed acquire below means the
    # lock is still held — leader is alive within TTL — so we keep waiting up to the hard cap.
    hard_deadline = time.monotonic() + SYNC_LOCK_MAX_WAIT_SECONDS
    while True:
        acquired = await redis.set(lock_key, lock_token, nx=True, ex=SYNC_LOCK_TTL_SECONDS)
        if acquired:
            break
        if time.monotonic() > hard_deadline:
            raise SyncFullCacheTimeoutError(
                f"Waited {SYNC_LOCK_MAX_WAIT_SECONDS}s for sync lock on integration {integration_id}"
            )
        if temporalio.activity.in_activity():
            temporalio.activity.heartbeat()
        await asyncio.sleep(SYNC_LOCK_POLL_INTERVAL_SECONDS)

    stop_heartbeat = asyncio.Event()
    # Captured here so the heartbeat (a separate task) can cancel the body if the lease is lost.
    parent_task = asyncio.current_task()

    async def _heartbeat() -> None:
        while not stop_heartbeat.is_set():
            try:
                await asyncio.wait_for(stop_heartbeat.wait(), timeout=SYNC_LOCK_HEARTBEAT_INTERVAL_SECONDS)
                return
            except TimeoutError:
                pass
            try:
                result = await redis.eval(_EXTEND_LOCK_SCRIPT, 1, lock_key, lock_token, str(SYNC_LOCK_TTL_SECONDS))
            except Exception:
                logger.exception("github_full_cache.sync_lock_heartbeat_failed", integration_id=integration_id)
                continue
            # Extend returned 0: the key is gone (TTL expired) or the token no longer matches
            # (another caller acquired it). Either way, we no longer own the lease — cancel
            # the body so a duplicate sync doesn't run alongside whoever now holds the lock.
            if not result:
                logger.warning(
                    "github_full_cache.sync_lock_lease_lost",
                    integration_id=integration_id,
                )
                if parent_task is not None and not parent_task.done():
                    parent_task.cancel()
                return

    # Ensure to keep the process alive through the heartbeats
    heartbeat_task = asyncio.create_task(_heartbeat())
    try:
        yield
    finally:
        stop_heartbeat.set()
        try:
            await heartbeat_task
        except (Exception, asyncio.CancelledError):
            logger.exception("github_full_cache.sync_lock_heartbeat_unexpected", integration_id=integration_id)
        # Shield the redis call so a cancellation arriving mid-flight doesn't abort the unlock.
        # Release is token-checked: no-op if our token no longer matches.
        try:
            await asyncio.shield(redis.eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, lock_token))
        except (Exception, asyncio.CancelledError):
            logger.exception("github_full_cache.sync_lock_release_failed", integration_id=integration_id)
