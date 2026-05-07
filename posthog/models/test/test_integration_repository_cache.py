import base64
import asyncio
from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.utils import timezone

from asgiref.sync import async_to_sync

from posthog.models.integration import GitHubIntegration, GitHubIntegrationError, Integration
from posthog.models.integration_repository_cache import (
    GITHUB_REPOSITORY_FULL_CACHE_TTL_SECONDS,
    SYNC_LOCK_KEY_PREFIX,
    GitHubRepositoryFullCache,
    IntegrationRepositoryCacheEntry,
    SyncFullCacheTimeoutError,
)


class TestGitHubRepositoryFullCache(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def _create_integration(self) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="github",
            config={"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            sensitive_config={"access_token": "ACCESS_TOKEN"},
        )

    def _readme_payload(self, text: str) -> dict:
        return {"content": base64.b64encode(text.encode("utf-8")).decode("ascii")}

    def _default_gh_api_responses(self, *, sha: str = "SHA1", readme: str = "# Hello", truncated: bool = False) -> dict:
        return {
            "/repos/posthog/posthog": {
                "default_branch": "main",
                "description": "PostHog open-source",
                "topics": ["analytics", "observability"],
                "archived": False,
                "fork": False,
                "language": "Python",
            },
            "/repos/posthog/posthog/branches/main": {"commit": {"sha": sha}},
            f"/repos/posthog/posthog/readme?ref={sha}": self._readme_payload(readme),
            f"/repos/posthog/posthog/git/trees/{sha}?recursive=1": {
                "tree": [
                    {"path": "README.md", "type": "blob"},
                    {"path": "src/app.py", "type": "blob"},
                    {"path": "src", "type": "tree"},  # non-blob is filtered out
                ],
                "truncated": truncated,
            },
        }

    def _patch_gh_api_get(self, responses: dict):
        def _side_effect(self_, path, *, endpoint=None, timeout=10):
            if path not in responses:
                raise AssertionError(f"unexpected path {path}")
            return responses[path]

        return patch(
            "posthog.models.integration.GitHubIntegration._gh_api_get", autospec=True, side_effect=_side_effect
        )

    def _cache_for(self, integration: Integration) -> GitHubRepositoryFullCache:
        return GitHubRepositoryFullCache(GitHubIntegration(integration))

    def test_sync_full_cache_entry_populates_all_fields(self):
        integration = self._create_integration()
        responses = self._default_gh_api_responses()

        with self._patch_gh_api_get(responses):
            entry = async_to_sync(self._cache_for(integration).sync_full_cache_entry_async)("posthog/posthog")

        assert entry.full_name == "posthog/posthog"
        assert entry.team_id == self.team.id
        assert entry.description == "PostHog open-source"
        assert entry.topics == ["analytics", "observability"]
        assert entry.archived is False
        assert entry.fork is False
        assert entry.primary_language == "Python"
        assert entry.default_branch == "main"
        assert entry.default_branch_sha == "SHA1"
        assert entry.readme == "# Hello"
        assert entry.tree_paths == "README.md\nsrc/app.py"
        assert entry.tree_truncated is False

    def test_sync_full_cache_entry_returns_cached_within_ttl_without_api_calls(self):
        integration = self._create_integration()
        IntegrationRepositoryCacheEntry.objects.create(
            integration=integration,
            team=self.team,
            full_name="posthog/posthog",
            default_branch="main",
            default_branch_sha="SHA1",
            readme="cached",
            tree_paths="old/path",
        )

        with patch("posthog.models.integration.GitHubIntegration._gh_api_get", autospec=True) as mock_gh_api_get:
            entry = async_to_sync(self._cache_for(integration).sync_full_cache_entry_async)("posthog/posthog")

        assert mock_gh_api_get.call_count == 0  # TTL short-circuits before any API calls
        assert entry.readme == "cached"
        assert entry.tree_paths == "old/path"

    def test_sync_full_cache_entry_refreshes_past_ttl(self):
        integration = self._create_integration()
        existing = IntegrationRepositoryCacheEntry.objects.create(
            integration=integration,
            team=self.team,
            full_name="posthog/posthog",
            default_branch="main",
            default_branch_sha="SHA1",
            readme="cached",
            tree_paths="old/path",
        )
        # Manually backdate the row past the TTL (auto_now=True blocks direct assignment).
        stale = timezone.now() - timedelta(seconds=GITHUB_REPOSITORY_FULL_CACHE_TTL_SECONDS + 60)
        IntegrationRepositoryCacheEntry.objects.filter(pk=existing.pk).update(updated_at=stale)

        responses = self._default_gh_api_responses(sha="SHA2", readme="# New README")
        with self._patch_gh_api_get(responses):
            entry = async_to_sync(self._cache_for(integration).sync_full_cache_entry_async)("posthog/posthog")

        assert entry.default_branch_sha == "SHA2"
        assert entry.readme == "# New README"
        assert entry.tree_paths == "README.md\nsrc/app.py"

    def test_sync_full_cache_entry_skips_readme_refetch_when_sha_unchanged(self):
        integration = self._create_integration()
        existing = IntegrationRepositoryCacheEntry.objects.create(
            integration=integration,
            team=self.team,
            full_name="posthog/posthog",
            description="stale description",
            topics=["old"],
            archived=False,
            fork=False,
            primary_language="Ruby",
            default_branch="main",
            default_branch_sha="SHA1",
            readme="cached",
            tree_paths="old/path",
            tree_truncated=False,
        )
        # Backdate past the TTL so we exercise the SHA light-path, not the TTL short-circuit.
        stale = timezone.now() - timedelta(seconds=GITHUB_REPOSITORY_FULL_CACHE_TTL_SECONDS + 60)
        IntegrationRepositoryCacheEntry.objects.filter(pk=existing.pk).update(updated_at=stale)

        responses = self._default_gh_api_responses(sha="SHA1")
        # Remove heavy endpoints to assert they are NOT called on the light path.
        responses.pop("/repos/posthog/posthog/readme?ref=SHA1")
        responses.pop("/repos/posthog/posthog/git/trees/SHA1?recursive=1")

        with self._patch_gh_api_get(responses):
            entry = async_to_sync(self._cache_for(integration).sync_full_cache_entry_async)("posthog/posthog")

        assert entry.description == "PostHog open-source"  # metadata updated
        assert entry.primary_language == "Python"
        assert entry.readme == "cached"  # readme unchanged
        assert entry.tree_paths == "old/path"

    def test_sync_full_cache_entry_refetches_when_sha_changed(self):
        integration = self._create_integration()
        existing = IntegrationRepositoryCacheEntry.objects.create(
            integration=integration,
            team=self.team,
            full_name="posthog/posthog",
            default_branch="main",
            default_branch_sha="SHA1",
            readme="old readme",
            tree_paths="old/path",
        )
        # Backdate past the TTL to skip the TTL short-circuit and reach the SHA check.
        stale = timezone.now() - timedelta(seconds=GITHUB_REPOSITORY_FULL_CACHE_TTL_SECONDS + 60)
        IntegrationRepositoryCacheEntry.objects.filter(pk=existing.pk).update(updated_at=stale)
        responses = self._default_gh_api_responses(sha="SHA2", readme="# New README")

        with self._patch_gh_api_get(responses):
            entry = async_to_sync(self._cache_for(integration).sync_full_cache_entry_async)("posthog/posthog")

        assert entry.default_branch_sha == "SHA2"
        assert entry.readme == "# New README"
        assert entry.tree_paths == "README.md\nsrc/app.py"

    def test_sync_full_cache_entry_handles_readme_fetch_failure_gracefully(self):
        integration = self._create_integration()
        responses = self._default_gh_api_responses()
        responses.pop("/repos/posthog/posthog/readme?ref=SHA1")

        call_log: list[str] = []

        def _side_effect(self_, path, *, endpoint=None, timeout=10):
            call_log.append(path)
            if path.startswith("/repos/posthog/posthog/readme"):
                raise GitHubIntegrationError("readme missing", status_code=404)
            return responses[path]

        with patch(
            "posthog.models.integration.GitHubIntegration._gh_api_get",
            autospec=True,
            side_effect=_side_effect,
        ):
            entry = async_to_sync(self._cache_for(integration).sync_full_cache_entry_async)("posthog/posthog")
            # Second sync should hit the TTL fast path — `readme=""` is a valid hydrated state for repos with no README.
            call_count_after_first = len(call_log)
            cached = async_to_sync(self._cache_for(integration).sync_full_cache_entry_async)("posthog/posthog")

        assert entry.readme == ""
        assert entry.tree_paths == "README.md\nsrc/app.py"
        assert cached.pk == entry.pk
        assert len(call_log) == call_count_after_first  # no further GitHub calls on second sync

    def test_sync_full_cache_entry_propagates_rate_limited_readme(self):
        integration = self._create_integration()
        responses = self._default_gh_api_responses()

        def _side_effect(self_, path, *, endpoint=None, timeout=10):
            if path.startswith("/repos/posthog/posthog/readme"):
                raise GitHubIntegrationError(
                    "secondary rate limit on /readme",
                    status_code=403,
                    is_rate_limit=True,
                    retry_after_seconds=60.0,
                )
            return responses[path]

        with patch(
            "posthog.models.integration.GitHubIntegration._gh_api_get",
            autospec=True,
            side_effect=_side_effect,
        ):
            with pytest.raises(GitHubIntegrationError) as excinfo:
                async_to_sync(self._cache_for(integration).sync_full_cache_entry_async)("posthog/posthog")

        assert excinfo.value.is_rate_limit is True
        assert excinfo.value.retry_after_seconds == 60.0
        assert not IntegrationRepositoryCacheEntry.objects.filter(integration=integration).exists()

    def test_sync_full_cache_entry_propagates_non_404_readme_errors(self):
        integration = self._create_integration()
        responses = self._default_gh_api_responses()

        def _side_effect(self_, path, *, endpoint=None, timeout=10):
            if path.startswith("/repos/posthog/posthog/readme"):
                raise GitHubIntegrationError("upstream 502 on /readme", status_code=502)
            return responses[path]

        with patch(
            "posthog.models.integration.GitHubIntegration._gh_api_get",
            autospec=True,
            side_effect=_side_effect,
        ):
            with pytest.raises(GitHubIntegrationError):
                async_to_sync(self._cache_for(integration).sync_full_cache_entry_async)("posthog/posthog")

        assert not IntegrationRepositoryCacheEntry.objects.filter(integration=integration).exists()

    def test_sync_full_cache_entry_url_encodes_branch_name_with_slash(self):
        integration = self._create_integration()
        responses = {
            "/repos/posthog/posthog": {
                "default_branch": "release/1.0",
                "description": "PostHog open-source",
                "topics": [],
                "archived": False,
                "fork": False,
                "language": "Python",
            },
            "/repos/posthog/posthog/branches/release%2F1.0": {"commit": {"sha": "SHA1"}},
            "/repos/posthog/posthog/readme?ref=SHA1": self._readme_payload("# Hello"),
            "/repos/posthog/posthog/git/trees/SHA1?recursive=1": {
                "tree": [{"path": "README.md", "type": "blob"}],
                "truncated": False,
            },
        }

        with self._patch_gh_api_get(responses):
            entry = async_to_sync(self._cache_for(integration).sync_full_cache_entry_async)("posthog/posthog")

        assert entry.default_branch == "release/1.0"
        assert entry.default_branch_sha == "SHA1"

    def test_sync_full_cache_entry_handles_truncated_tree(self):
        integration = self._create_integration()
        responses = self._default_gh_api_responses(truncated=True)

        with self._patch_gh_api_get(responses):
            entry = async_to_sync(self._cache_for(integration).sync_full_cache_entry_async)("posthog/posthog")

        assert entry.tree_truncated is True

    def test_sync_full_cache_entry_raises_on_missing_branch_sha(self):
        integration = self._create_integration()
        responses = self._default_gh_api_responses()
        responses["/repos/posthog/posthog/branches/main"] = {"commit": {}}  # missing sha

        with self._patch_gh_api_get(responses), pytest.raises(GitHubIntegrationError, match="missing commit sha"):
            async_to_sync(self._cache_for(integration).sync_full_cache_entry_async)("posthog/posthog")

    def test_sync_full_cache_entry_rejects_bare_name(self):
        integration = self._create_integration()

        with pytest.raises(ValueError, match="'owner/repo' format"):
            async_to_sync(self._cache_for(integration).sync_full_cache_entry_async)("posthog")

    def test_sync_full_cache_runs_with_bounded_concurrency(self):
        integration = self._create_integration()

        observed_in_flight: list[int] = []
        in_flight = 0
        lock = asyncio.Lock()

        async def fake_entry_async(full_name, *, path_log=None):
            nonlocal in_flight
            async with lock:
                in_flight += 1
                observed_in_flight.append(in_flight)
            await asyncio.sleep(0.01)
            async with lock:
                in_flight -= 1
            return MagicMock(full_name=full_name)

        repos = [{"full_name": f"posthog/repo-{i}"} for i in range(20)]

        async def fake_list():
            return repos

        repo_cache = self._cache_for(integration)
        with (
            patch.object(repo_cache, "sync_full_cache_entry_async", side_effect=fake_entry_async),
            patch.object(repo_cache.github, "list_all_cached_repositories_async", side_effect=fake_list),
        ):
            results = asyncio.run(repo_cache.sync_full_cache(concurrency=3))

        assert len(results) == 20
        assert max(observed_in_flight) <= 3

    def test_sync_full_cache_returns_exceptions_inline(self):
        integration = self._create_integration()

        async def fake_entry_async(full_name, *, path_log=None):
            if full_name == "posthog/broken":
                raise GitHubIntegrationError("boom")
            return MagicMock(full_name=full_name)

        async def fake_list():
            return [{"full_name": "posthog/ok"}, {"full_name": "posthog/broken"}]

        repo_cache = self._cache_for(integration)
        with (
            patch.object(repo_cache, "sync_full_cache_entry_async", side_effect=fake_entry_async),
            patch.object(repo_cache.github, "list_all_cached_repositories_async", side_effect=fake_list),
        ):
            results = asyncio.run(repo_cache.sync_full_cache())

        assert len(results) == 2
        broken = next(r for r in results if isinstance(r, GitHubIntegrationError))
        assert str(broken) == "boom"

    def test_sync_full_cache_evicts_orphans_not_in_light_cache(self):
        integration = self._create_integration()
        # Seed: one repo still in the light list ("posthog/posthog") and one orphan ("posthog/gone").
        IntegrationRepositoryCacheEntry.objects.create(
            integration=integration,
            team=self.team,
            full_name="posthog/posthog",
            default_branch="main",
            default_branch_sha="SHA1",
            readme="cached",
        )
        IntegrationRepositoryCacheEntry.objects.create(
            integration=integration,
            team=self.team,
            full_name="posthog/gone",
            default_branch="main",
            default_branch_sha="SHA_GONE",
            readme="cached",
        )

        async def fake_entry_async(full_name, *, path_log=None):
            return MagicMock(full_name=full_name)

        async def fake_list():
            return [{"full_name": "posthog/posthog"}]  # posthog/gone removed

        repo_cache = self._cache_for(integration)
        with (
            patch.object(repo_cache, "sync_full_cache_entry_async", side_effect=fake_entry_async),
            patch.object(repo_cache.github, "list_all_cached_repositories_async", side_effect=fake_list),
        ):
            # async_to_sync keeps thread-sensitive DB ops on the test thread so they see
            # the rows created above inside the TestCase transaction.
            async_to_sync(repo_cache.sync_full_cache)()

        remaining = set(integration.repository_cache_entries.values_list("full_name", flat=True))
        assert remaining == {"posthog/posthog"}

    def test_sync_full_cache_evicts_all_when_light_cache_is_empty(self):
        integration = self._create_integration()
        IntegrationRepositoryCacheEntry.objects.create(
            integration=integration,
            team=self.team,
            full_name="posthog/gone",
            default_branch="main",
            default_branch_sha="SHA_GONE",
            readme="cached",
        )

        async def fake_list():
            return []

        repo_cache = self._cache_for(integration)
        with patch.object(repo_cache.github, "list_all_cached_repositories_async", side_effect=fake_list):
            results = async_to_sync(repo_cache.sync_full_cache)()

        assert results == []
        assert not integration.repository_cache_entries.exists()

    def test_sync_full_cache_entry_lowercases_mixed_case_input(self):
        # Same row regardless of input casing — guards against `(integration, full_name)` drift.
        integration = self._create_integration()
        responses = self._default_gh_api_responses()
        cache_obj = self._cache_for(integration)

        with self._patch_gh_api_get(responses):
            first = async_to_sync(cache_obj.sync_full_cache_entry_async)("PostHog/PostHog")
            second = async_to_sync(cache_obj.sync_full_cache_entry_async)("posthog/posthog")

        assert first.full_name == "posthog/posthog"
        assert first.pk == second.pk
        assert integration.repository_cache_entries.count() == 1

    def test_sync_full_cache_lowercases_orphan_eviction_set(self):
        # Light cache returns mixed case; existing rows are lowercase. Eviction must match across cases.
        integration = self._create_integration()
        keep = IntegrationRepositoryCacheEntry.objects.create(
            integration=integration,
            team=self.team,
            full_name="posthog/posthog",
            default_branch="main",
            default_branch_sha="SHA1",
            readme="cached",
        )

        async def fake_entry_async(full_name, *, path_log=None):
            return MagicMock(full_name=full_name)

        async def fake_list():
            # GitHub returns "PostHog/posthog" — must still match the lowercased seed row.
            return [{"full_name": "PostHog/posthog"}]

        repo_cache = self._cache_for(integration)
        with (
            patch.object(repo_cache, "sync_full_cache_entry_async", side_effect=fake_entry_async),
            patch.object(repo_cache.github, "list_all_cached_repositories_async", side_effect=fake_list),
        ):
            async_to_sync(repo_cache.sync_full_cache)()

        assert IntegrationRepositoryCacheEntry.objects.filter(pk=keep.pk).exists()


class TestSyncFullCacheLock(BaseTest):
    """Cover the single-flight Redis lock around `sync_full_cache`."""

    def setUp(self):
        super().setUp()
        cache.clear()

    def _create_integration(self) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="github",
            config={"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            sensitive_config={"access_token": "ACCESS_TOKEN"},
        )

    def _cache_for(self, integration: Integration) -> GitHubRepositoryFullCache:
        return GitHubRepositoryFullCache(GitHubIntegration(integration))

    # In TEST mode `posthog.redis.get_client()` and `get_async_client()` return separate
    # fakeredis instances with no shared state, so these tests use the async client throughout.

    def test_acquires_lock_and_releases_on_success(self):
        integration = self._create_integration()
        repo_cache = self._cache_for(integration)

        async def fake_list():
            return []

        from posthog import redis as posthog_redis

        async def run_and_check():
            await repo_cache.sync_full_cache()
            redis = posthog_redis.get_async_client()
            return await redis.get(f"{SYNC_LOCK_KEY_PREFIX}:{integration.id}")

        with patch.object(repo_cache.github, "list_all_cached_repositories_async", side_effect=fake_list):
            assert asyncio.run(run_and_check()) is None  # lock released after success

    def test_follower_waits_then_runs_after_leader_releases(self):
        # Leader holds the lock briefly; follower's first SET fails, retries succeed after release.
        integration = self._create_integration()

        from posthog import redis as posthog_redis
        from posthog.models.integration_repository_cache import _acquire_sync_lock

        lock_key = f"{SYNC_LOCK_KEY_PREFIX}:{integration.id}"

        async def scenario():
            redis = posthog_redis.get_async_client()
            await redis.set(lock_key, "leader-token", ex=60)

            async def release_after_delay():
                await asyncio.sleep(0.2)
                await redis.delete(lock_key)

            release_task = asyncio.create_task(release_after_delay())
            try:
                async with _acquire_sync_lock(integration.id):
                    pass
            finally:
                await release_task
            return await redis.get(lock_key)

        with patch("posthog.models.integration_repository_cache.SYNC_LOCK_POLL_INTERVAL_SECONDS", 0.05):
            assert asyncio.run(scenario()) is None

    def test_follower_times_out_when_leader_never_releases(self):
        integration = self._create_integration()
        from posthog import redis as posthog_redis
        from posthog.models.integration_repository_cache import _acquire_sync_lock

        lock_key = f"{SYNC_LOCK_KEY_PREFIX}:{integration.id}"

        async def scenario():
            redis = posthog_redis.get_async_client()
            await redis.set(lock_key, "stuck-leader", ex=60)
            try:
                async with _acquire_sync_lock(integration.id):
                    pass
            finally:
                # Stuck leader's lock untouched after follower gives up.
                value = await redis.get(lock_key)
                await redis.delete(lock_key)
                assert value == b"stuck-leader"

        with (
            patch("posthog.models.integration_repository_cache.SYNC_LOCK_POLL_INTERVAL_SECONDS", 0.05),
            patch("posthog.models.integration_repository_cache.SYNC_LOCK_MAX_WAIT_SECONDS", 0.15),
        ):
            with pytest.raises(SyncFullCacheTimeoutError):
                asyncio.run(scenario())

    def test_heartbeat_cancels_body_when_lease_is_lost(self):
        # Once another caller has taken over the lock, the heartbeat must cancel the in-flight body
        # so duplicate syncs can't run side-by-side.
        integration = self._create_integration()
        from posthog import redis as posthog_redis
        from posthog.models.integration_repository_cache import _acquire_sync_lock

        lock_key = f"{SYNC_LOCK_KEY_PREFIX}:{integration.id}"

        async def scenario():
            redis = posthog_redis.get_async_client()
            async with _acquire_sync_lock(integration.id):
                # Simulate another caller acquiring the lock after our TTL expired.
                await redis.set(lock_key, "another-token", ex=60)
                # Long enough for at least one heartbeat tick to fire and notice.
                await asyncio.sleep(0.5)

        with patch("posthog.models.integration_repository_cache.SYNC_LOCK_HEARTBEAT_INTERVAL_SECONDS", 0.05):
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(scenario())

    def test_lock_released_when_body_is_cancelled(self):
        # Cancellation during the body must not leak the Redis key — the release runs in the
        # finally block, shielded so a cancel arriving mid-redis-call still completes.
        import contextlib

        integration = self._create_integration()
        from posthog import redis as posthog_redis
        from posthog.models.integration_repository_cache import _acquire_sync_lock

        lock_key = f"{SYNC_LOCK_KEY_PREFIX}:{integration.id}"

        async def scenario():
            async def hold_lock():
                async with _acquire_sync_lock(integration.id):
                    await asyncio.sleep(10)

            task = asyncio.create_task(hold_lock())
            await asyncio.sleep(0.05)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            redis = posthog_redis.get_async_client()
            return await redis.get(lock_key)

        assert asyncio.run(scenario()) is None
