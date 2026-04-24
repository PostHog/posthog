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
import base64
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TYPE_CHECKING
from urllib.parse import quote

from django.db import models
from django.utils import timezone

import structlog

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

    def sync_full_cache_entry(self, full_name: str) -> IntegrationRepositoryCacheEntry:
        """Fetch one repo's heavy metadata + README + file tree, upsert the cache row."""
        # 1. Validate input.
        if "/" not in full_name:
            raise ValueError(f"full_name must be in 'owner/repo' format, got {full_name!r}")
        owner, repo = full_name.split("/", 1)
        start = time.monotonic()

        # 2. TTL gate: fresh row → skip GitHub entirely.
        existing = (
            # Avoid pulling heavy stuff as we don't need to check freshness
            self.integration.repository_cache_entries.filter(full_name=full_name).defer("readme", "tree_paths").first()
        )
        if existing and existing.default_branch_sha and self._is_fresh(existing):
            logger.info(
                "github_full_cache.sync_repo",
                integration_id=self.integration.id,
                full_name=full_name,
                ttl_hit=True,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            return existing

        # 3. Fetch repo metadata + default-branch SHA (cheap; needed to choose light vs heavy path).
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
        # 4. Light path: SHA unchanged → refresh only mutable metadata, skip README/tree.
        if existing and existing.default_branch_sha == default_branch_sha:
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
            logger.info(
                "github_full_cache.sync_repo",
                integration_id=self.integration.id,
                full_name=full_name,
                sha_unchanged=True,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            return existing
        # 5. Heavy path
        # 5a. Best-effort README (404 is normal — repos without one stay with empty string).
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
            logger.info(
                "github_full_cache.readme_missing",
                integration_id=self.integration.id,
                full_name=full_name,
            )
        # 5b. Recursive file tree → newline-separated blob paths for ARRAY JOIN grep.
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
        # 6. Upsert the cache row.
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
                "tree_truncated": bool(tree_data.get("truncated", False)),
            },
        )
        logger.info(
            "github_full_cache.sync_repo",
            integration_id=self.integration.id,
            full_name=full_name,
            sha_unchanged=False,
            tree_truncated=entry.tree_truncated,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return entry

    @database_sync_to_async
    def sync_full_cache_entry_async(self, full_name: str) -> IntegrationRepositoryCacheEntry:
        return self.sync_full_cache_entry(full_name)

    @database_sync_to_async
    def _evict_orphans(self, valid_full_names: set[str]) -> int:
        deleted, _ = self.integration.repository_cache_entries.exclude(full_name__in=valid_full_names).delete()
        return deleted

    async def sync_full_cache(self, *, concurrency: int = 10) -> list[IntegrationRepositoryCacheEntry | BaseException]:
        """Bulk heavy sync for all repos this integration sees.

        The light JSONField cache (``Integration.repository_cache``) is the authoritative
        set — rows for repos no longer in it are deleted before syncing.
        """
        # 1. Source of truth: the light cache. This also refreshes it from GitHub if >1h stale.
        repos = await self.github.list_all_cached_repositories_async()
        valid_full_names = {r["full_name"] for r in repos if isinstance(r.get("full_name"), str)}
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

        def make_fn(full_name: str) -> Callable[[], Awaitable[IntegrationRepositoryCacheEntry]]:
            async def run() -> IntegrationRepositoryCacheEntry:
                return await self.sync_full_cache_entry_async(full_name)

            return run

        # 3. Sync each remaining repo with bounded concurrency + rate-limit-aware backoff.
        return await run_parallel_with_backoff(
            [make_fn(name) for name in valid_full_names],
            concurrency=concurrency,
            is_retryable=lambda exc: isinstance(exc, GitHubIntegrationError) and exc.is_rate_limit,
            get_retry_delay=lambda exc: getattr(exc, "retry_after_seconds", None),
        )
