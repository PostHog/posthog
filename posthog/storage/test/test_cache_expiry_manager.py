import json
import time
from uuid import uuid4

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, call, patch

from django.core.cache import caches
from django.test import SimpleTestCase, override_settings

from celery.exceptions import SoftTimeLimitExceeded
from parameterized import parameterized

from posthog.dbrouter import ReplicaRouter
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.storage import object_storage
from posthog.storage.cache_expiry_manager import (
    ExpiringTeamSelection,
    RefreshPacing,
    cleanup_stale_expiry_tracking,
    refresh_expiring_caches,
    select_expiring_teams,
)
from posthog.storage.hypercache_manager import HyperCacheManagementConfig
from posthog.storage.test.test_hypercache_manager import (
    create_test_config as build_config,
    create_test_hypercache,
)

MODULE = "posthog.storage.cache_expiry_manager"


def build_teams(count: int) -> list[Team]:
    return [Team(id=team_id) for team_id in range(1, count + 1)]


class TestRefreshExpiringCaches(SimpleTestCase):
    def setUp(self):
        super().setUp()

        select_patcher = patch(f"{MODULE}.select_expiring_teams")
        self.mock_select = select_patcher.start()
        self.addCleanup(select_patcher.stop)
        self.given_teams(3)

        redis_patcher = patch(f"{MODULE}.get_client")
        self.mock_get_client = redis_patcher.start()
        self.addCleanup(redis_patcher.stop)
        self.mock_redis = self.mock_get_client.return_value
        self.mock_redis.zcount.return_value = 0
        self.mock_redis.zrange.return_value = []

        push_patcher = patch(f"{MODULE}.push_hypercache_teams_processed_metrics")
        self.mock_push = push_patcher.start()
        self.addCleanup(push_patcher.stop)

        # Patch the module's `time`, not `time.sleep` on the stdlib module object:
        # `cache_expiry_manager` does `import time`, so patching the attribute reaches
        # every other importer for the duration of the test. The real clock is kept,
        # because the backlog threshold is computed from `time.time()`.
        time_patcher = patch(f"{MODULE}.time")
        mock_time = time_patcher.start()
        mock_time.time.side_effect = time.time
        self.mock_sleep = mock_time.sleep
        self.addCleanup(time_patcher.stop)

    def given_teams(self, count: int, limit_reached: bool = False) -> None:
        self.mock_select.return_value = ExpiringTeamSelection(teams=build_teams(count), limit_reached=limit_reached)

    def test_without_a_routing_hook_every_team_is_built(self):
        update_fn = MagicMock(return_value=True)

        counts = refresh_expiring_caches(build_config(update_fn=update_fn))

        assert update_fn.call_count == 3
        assert (counts.successful, counts.failed, counts.enqueued) == (3, 0, 0)

    def test_a_hook_that_declines_a_team_leaves_the_build_to_the_update_fn(self):
        update_fn = MagicMock(return_value=True)
        route_refresh_fn = MagicMock(return_value=False)

        counts = refresh_expiring_caches(build_config(update_fn=update_fn, route_refresh_fn=route_refresh_fn))

        assert route_refresh_fn.call_count == 3
        assert update_fn.call_count == 3
        assert (counts.successful, counts.failed, counts.enqueued) == (3, 0, 0)

    def test_a_routed_team_is_not_built_and_is_counted_as_enqueued(self):
        update_fn = MagicMock(return_value=True)

        counts = refresh_expiring_caches(
            build_config(update_fn=update_fn, route_refresh_fn=MagicMock(return_value=True))
        )

        update_fn.assert_not_called()
        assert (counts.successful, counts.failed, counts.enqueued) == (0, 0, 3)

    def test_the_three_counts_sum_to_the_teams_the_run_processed(self):
        self.given_teams(4)
        # Team 1 routed, team 2 built, team 3 reported as a failed build, team 4 raised.
        route_refresh_fn = MagicMock(side_effect=[True, False, False, False])
        update_fn = MagicMock(side_effect=[True, False, RuntimeError("redis down")])

        counts = refresh_expiring_caches(build_config(update_fn=update_fn, route_refresh_fn=route_refresh_fn))

        assert (counts.successful, counts.failed, counts.enqueued) == (1, 2, 1)
        assert counts.successful + counts.failed + counts.enqueued == 4

    def test_a_cache_that_has_not_opted_in_keeps_its_flat_ttl(self) -> None:
        update_fn = MagicMock(return_value=True)
        config = build_config(update_fn=update_fn, cache_ttl=1000)

        with patch(f"{MODULE}.random.randint") as mock_randint:
            refresh_expiring_caches(config)

        assert mock_randint.call_count == 0
        assert [c.kwargs["ttl"] for c in update_fn.call_args_list] == [None, None, None]

    @parameterized.expand(
        [
            ("a_fraction_of_the_cache_ttl", 1000, 0.7, (700, 1000), 850),
            # The floor truncates to an int, so without a clamp this band starts at zero
            # and can draw a ttl of 0, which Redis expires on arrival.
            ("at_least_one_second", 60, 0.01, (1, 60), 30),
        ]
    )
    def test_an_opted_in_cache_draws_its_ttl_from_the_band_above_the_floor(
        self, _name: str, cache_ttl: int, fraction: float, expected_band: tuple[int, int], drawn: int
    ) -> None:
        update_fn = MagicMock(return_value=True)
        config = build_config(update_fn=update_fn, refresh_ttl_min_fraction=fraction, cache_ttl=cache_ttl)

        with patch(f"{MODULE}.random.randint", return_value=drawn) as mock_randint:
            refresh_expiring_caches(config)

        assert mock_randint.call_args_list == [call(*expected_band)] * 3
        assert [c.kwargs["ttl"] for c in update_fn.call_args_list] == [drawn] * 3

    def test_a_hook_that_raises_counts_as_failed_and_does_not_build(self):
        update_fn = MagicMock(return_value=True)
        route_refresh_fn = MagicMock(side_effect=RuntimeError("flag client down"))

        counts = refresh_expiring_caches(build_config(update_fn=update_fn, route_refresh_fn=route_refresh_fn))

        update_fn.assert_not_called()
        assert (counts.successful, counts.failed, counts.enqueued) == (0, 3, 0)

    @parameterized.expand(
        [
            # The ninth team completes a chunk but is last, so nothing waits behind it.
            # A team count that is not a multiple of the chunk never reaches that branch.
            ("all_routed", [True] * 9, 3, [5, 5]),
            # A partial ramp is the run this will actually make, and it is the only one
            # that separates "every third routed team" from "every third team": the
            # built teams must not advance the chunk counter.
            ("half_routed", [True, False, True, False, True, False], 2, [5]),
            ("none_routed", [False] * 3, 1, []),
        ]
    )
    def test_pacing_pauses_once_per_chunk_of_routed_teams(self, _name, routed, chunk_size, expected_delays):
        self.given_teams(len(routed))

        refresh_expiring_caches(
            build_config(route_refresh_fn=MagicMock(side_effect=routed)),
            pacing=RefreshPacing(chunk_size=chunk_size, delay_seconds=5, window_seconds=600),
        )

        assert [call.args[0] for call in self.mock_sleep.call_args_list] == expected_delays

    def test_pacing_stops_once_the_window_is_spent(self):
        self.given_teams(5)

        refresh_expiring_caches(
            build_config(route_refresh_fn=MagicMock(return_value=True)),
            pacing=RefreshPacing(chunk_size=1, delay_seconds=6, window_seconds=10),
        )

        # The second pause is trimmed to what the window has left, and nothing waits after.
        assert [call.args[0] for call in self.mock_sleep.call_args_list] == [6, 4]

    def test_the_backlog_gauge_is_not_capped_by_the_run_limit(self):
        self.mock_redis.zcount.return_value = 9000

        refresh_expiring_caches(build_config(), limit=3)

        assert self.mock_push.call_args.kwargs["expiry_backlog"] == 9000
        # Counting a different key or a capped range would still satisfy the value
        # assertion above, so pin which set the gauge reads.
        assert self.mock_redis.zcount.call_args.args[0] == "test_cache_expiry"
        assert self.mock_redis.zcount.call_args.args[1] == "-inf"

    def test_the_before_sample_is_taken_before_any_team_is_processed(self) -> None:
        backlog = [9000]
        self.mock_redis.zcount.side_effect = lambda *args, **kwargs: backlog[0]

        def route_refresh_fn(_team_id: int) -> bool:
            backlog[0] = 0
            return True

        refresh_expiring_caches(build_config(route_refresh_fn=route_refresh_fn))

        push_kwargs = self.mock_push.call_args.kwargs
        # A before sample taken after the run starts reads whatever the run has already
        # done to the sorted set, which is the ambiguity this pair of samples removes.
        assert push_kwargs["expiry_backlog_before"] == 9000
        assert push_kwargs["expiry_backlog"] == 0

    @parameterized.expand(
        [
            ("due_in_an_hour", 3600),
            ("an_hour_past_expiry", -3600),
        ]
    )
    def test_the_oldest_entry_is_reported_as_seconds_until_its_expiry(self, _name: str, seconds_to_expiry: int) -> None:
        # The two reads are the before and after samples. Only the before one is pushed,
        # so they have to differ or forwarding the wrong sample passes this test.
        self.mock_redis.zrange.side_effect = [
            [(b"7", time.time() + seconds_to_expiry)],
            [(b"7", time.time() + 86400)],
        ]

        refresh_expiring_caches(build_config())

        self.assertAlmostEqual(self.mock_push.call_args.kwargs["oldest_expiry_seconds"], seconds_to_expiry, delta=5)
        # The lowest score is the entry closest to expiry. Reading the other end of the
        # set reports the healthiest entry and hides a sweep that is falling behind.
        assert self.mock_redis.zrange.call_args.args == ("test_cache_expiry", 0, 0)
        assert self.mock_redis.zrange.call_args.kwargs == {"withscores": True}

    def test_an_empty_sorted_set_reports_no_oldest_entry(self) -> None:
        self.mock_redis.zrange.return_value = []

        refresh_expiring_caches(build_config())

        assert self.mock_push.call_args.kwargs["oldest_expiry_seconds"] is None

    @parameterized.expand([("saturated", True), ("drained", False)])
    def test_the_run_reports_whether_its_selection_filled(self, _name: str, limit_reached: bool) -> None:
        self.given_teams(3, limit_reached=limit_reached)

        refresh_expiring_caches(build_config())

        assert self.mock_push.call_args.kwargs["limit_reached"] is limit_reached

    def test_an_empty_run_still_reports_its_counts_and_backlog(self):
        self.given_teams(0)
        self.mock_redis.zcount.return_value = 0

        refresh_expiring_caches(build_config())

        push_kwargs = self.mock_push.call_args.kwargs
        assert push_kwargs["successful"] == 0
        assert push_kwargs["failed"] == 0
        assert push_kwargs["enqueued"] == 0
        assert push_kwargs["expiry_backlog"] == 0
        assert push_kwargs["expiry_backlog_before"] == 0

    def test_an_unreadable_backlog_pushes_no_backlog_value(self):
        self.mock_get_client.side_effect = RuntimeError("redis unreachable")

        refresh_expiring_caches(build_config())

        push_kwargs = self.mock_push.call_args.kwargs
        assert push_kwargs["expiry_backlog"] is None
        assert push_kwargs["expiry_backlog_before"] is None
        assert push_kwargs["oldest_expiry_seconds"] is None

    def test_an_unreadable_oldest_entry_still_reports_the_count(self) -> None:
        self.mock_redis.zcount.return_value = 9000
        self.mock_redis.zrange.side_effect = RuntimeError("redis timed out")

        refresh_expiring_caches(build_config())

        # A zrange failure must not discard a zcount that already succeeded.
        push_kwargs = self.mock_push.call_args.kwargs
        assert push_kwargs["expiry_backlog_before"] == 9000
        assert push_kwargs["oldest_expiry_seconds"] is None


@override_settings(
    OBJECT_STORAGE_ENABLED=True,
    CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        "mirror": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "expiry-cleanup-mirror"},
    },
)
class TestCleanupStaleExpiryTracking(BaseTest):
    def given_cache(self, token_based: bool, mirror: bool = True) -> None:
        self.sorted_set_key = f"expiry_cleanup_test_{uuid4().hex}"
        self.hypercache = create_test_hypercache(
            namespace=f"expiry_cleanup_test_{uuid4().hex}",
            token_based=token_based,
            expiry_sorted_set_key=self.sorted_set_key,
        )
        # Remote config and flag definitions mirror every write and delete to a secondary cache.
        # The flags and team metadata caches have no mirror.
        if mirror:
            self.hypercache.secondary_cache_client = caches["mirror"]
        self.config = HyperCacheManagementConfig(
            hypercache=self.hypercache, update_fn=lambda team, ttl=None: True, cache_name="test_cache"
        )
        self.redis = get_client(self.hypercache.redis_url)

    def write_entry(self, team: Team) -> None:
        self.hypercache.set_cache_value(team, {"id": team.id})
        self.addCleanup(self.hypercache.delete_cache_entry, self.hypercache.get_cache_identifier(team))

    def deleted_team(self) -> Team:
        return Team(id=self.team.id + 100000, api_token=f"phc_deleted_{uuid4().hex}")

    def entry_state(self, team: Team) -> tuple[bool, bool, bool]:
        identifier = self.hypercache.get_cache_identifier(team)
        key = self.hypercache.get_cache_key(identifier)
        return (
            self.hypercache.cache_client.get(key) is not None,
            object_storage.read(key, missing_ok=True) is not None,
            self.redis.zscore(self.sorted_set_key, str(identifier)) is not None,
        )

    @parameterized.expand(
        [
            ("token_based", True, True, True),
            ("id_based", False, True, True),
            ("without_object_storage", True, False, True),
            ("id_based_without_a_mirror", False, True, False),
        ]
    )
    def test_deletes_the_entry_of_a_deleted_team_and_keeps_a_live_one(
        self, _name: str, token_based: bool, object_storage_enabled: bool, mirror: bool
    ) -> None:
        with override_settings(OBJECT_STORAGE_ENABLED=object_storage_enabled):
            self.given_cache(token_based, mirror=mirror)
            deleted_team = self.deleted_team()
            self.write_entry(self.team)
            self.write_entry(deleted_team)

            # The "replica" alias does not exist. A Team read that follows the router raises.
            # The existence check must read the primary, because a lagging replica can report a
            # new team as missing.
            with override_settings(DATABASE_ROUTERS=[ReplicaRouter(["Team"])]):
                removed = cleanup_stale_expiry_tracking(self.config)

            assert removed == 1
            assert self.entry_state(deleted_team) == (False, False, False)
            assert self.entry_state(self.team) == (True, object_storage_enabled, True)

    @parameterized.expand(
        [
            ("primary", "cache_client", (True, False, True)),
            ("secondary", "secondary_cache_client", (False, False, True)),
        ]
    )
    def test_a_failed_redis_delete_keeps_the_entry_tracked_for_the_next_cleanup(
        self, _name: str, failing_client_attr: str, state_after_failure: tuple[bool, bool, bool]
    ) -> None:
        self.given_cache(token_based=True)
        failing_team = self.deleted_team()
        other_deleted_team = Team(id=self.team.id + 100001, api_token=f"phc_deleted_{uuid4().hex}")
        self.write_entry(failing_team)
        self.write_entry(other_deleted_team)
        failing_client = getattr(self.hypercache, failing_client_attr)
        failing_key = self.hypercache.get_cache_key(failing_team)
        real_delete = failing_client.delete

        def fail_for_one_key(key, *args, **kwargs):
            if key == failing_key:
                raise ConnectionError("down")
            return real_delete(key, *args, **kwargs)

        with patch.object(failing_client, "delete", side_effect=fail_for_one_key):
            removed = cleanup_stale_expiry_tracking(self.config)

        # One entry's failure must not stop the cleanup of the others.
        assert removed == 1
        assert self.entry_state(other_deleted_team) == (False, False, False)
        # The object-storage copy has no TTL. The cleanup deletes it even though a Redis delete failed.
        assert self.entry_state(failing_team) == state_after_failure
        assert failing_client.get(failing_key) is not None

        assert cleanup_stale_expiry_tracking(self.config) == 1
        assert self.entry_state(failing_team) == (False, False, False)
        assert failing_client.get(failing_key) is None

    @parameterized.expand(
        [
            ("new_score", 60, (), (True, True, True)),
            ("same_score", 0, (), (True, True, True)),
            ("only_object_storage_holds_it", 0, ("primary", "mirror"), (False, True, True)),
            ("only_the_mirror_holds_it", 0, ("primary", "object_storage"), (False, False, True)),
        ]
    )
    def test_an_entry_rewritten_during_the_cleanup_stays_tracked(
        self,
        _name: str,
        extra_ttl: int,
        tiers_deleted_after_rewrite: tuple[str, ...],
        state_after_cleanup: tuple[bool, bool, bool],
    ) -> None:
        self.given_cache(token_based=True)
        deleted_team = self.deleted_team()
        mirror = self.hypercache.secondary_cache_client
        assert mirror is not None
        delete_object = object_storage.delete

        def delete_then_rewrite(key: str) -> None:
            delete_object(key)
            # A refresh run that loaded the team before it was deleted writes the entry again.
            # Within the same second and with the same TTL, the rewrite gets the score the cleanup read.
            self.hypercache.set_cache_value(
                deleted_team, {"id": deleted_team.id}, ttl=self.hypercache.cache_ttl + extra_ttl
            )
            # A rewrite that interleaves with the cleanup's deletes can survive in only some tiers.
            if "primary" in tiers_deleted_after_rewrite:
                self.hypercache.cache_client.delete(key)
            if "mirror" in tiers_deleted_after_rewrite:
                mirror.delete(key)
            if "object_storage" in tiers_deleted_after_rewrite:
                delete_object(key)

        key = self.hypercache.get_cache_key(deleted_team)
        with time_machine.travel(time.time(), tick=False):
            self.write_entry(deleted_team)
            with patch("posthog.storage.hypercache.object_storage.delete", side_effect=delete_then_rewrite):
                assert cleanup_stale_expiry_tracking(self.config) == 0

        assert self.entry_state(deleted_team) == state_after_cleanup
        assert (mirror.get(key) is not None) == ("mirror" not in tiers_deleted_after_rewrite)

        assert cleanup_stale_expiry_tracking(self.config) == 1
        assert self.entry_state(deleted_team) == (False, False, False)
        assert mirror.get(key) is None

    @parameterized.expand(
        [
            ("primary", (True, False, True), True),
            ("object_storage", (False, True, True), False),
            ("mirror", (False, False, True), True),
        ]
    )
    def test_an_entry_restored_without_a_new_score_stays_tracked(
        self, tier: str, state_after_cleanup: tuple[bool, bool, bool], mirror_holds_it: bool
    ) -> None:
        self.given_cache(token_based=True)
        deleted_team = self.deleted_team()
        self.write_entry(deleted_team)
        mirror = self.hypercache.secondary_cache_client
        assert mirror is not None
        delete_object = object_storage.delete
        data = {"id": deleted_team.id}

        def delete_then_restore(key: str) -> None:
            delete_object(key)
            # A read between the Redis delete and the object-storage delete copies the object back
            # into Redis. A rewrite whose own add failed leaves a copy in any tier. Neither path
            # adds the member again.
            if tier == "primary":
                self.hypercache._set_cache_value_redis(deleted_team, data)
            elif tier == "object_storage":
                self.hypercache._set_cache_value_s3(deleted_team, data)
            else:
                mirror.set(key, json.dumps(data))

        key = self.hypercache.get_cache_key(deleted_team)
        with patch("posthog.storage.hypercache.object_storage.delete", side_effect=delete_then_restore):
            assert cleanup_stale_expiry_tracking(self.config) == 0

        assert self.entry_state(deleted_team) == state_after_cleanup
        assert (mirror.get(key) is not None) == mirror_holds_it

        assert cleanup_stale_expiry_tracking(self.config) == 1
        assert self.entry_state(deleted_team) == (False, False, False)
        assert mirror.get(key) is None

    @parameterized.expand(
        [
            ("during_a_delete", "posthog.storage.hypercache.HyperCache.delete_cache_entry"),
            ("during_the_team_lookup", f"{MODULE}.existing_team_identifiers"),
        ]
    )
    def test_a_soft_time_limit_stops_the_cleanup(self, _name: str, target: str) -> None:
        self.given_cache(token_based=True)
        self.write_entry(self.deleted_team())

        with patch(target, side_effect=SoftTimeLimitExceeded()), pytest.raises(SoftTimeLimitExceeded):
            cleanup_stale_expiry_tracking(self.config)

    def test_a_failed_existence_check_keeps_the_entry_tracked_for_the_next_cleanup(self) -> None:
        self.given_cache(token_based=True)
        deleted_team = self.deleted_team()
        self.write_entry(deleted_team)

        with patch(
            "posthog.storage.cache_expiry_manager.object_storage.head_object_strict",
            side_effect=object_storage.ObjectStorageError("down"),
        ):
            assert cleanup_stale_expiry_tracking(self.config) == 0

        assert self.entry_state(deleted_team) == (False, False, True)

        assert cleanup_stale_expiry_tracking(self.config) == 1
        assert self.entry_state(deleted_team) == (False, False, False)

    def test_a_failed_untrack_keeps_the_entry_tracked_outside_the_refresh_window(self) -> None:
        self.given_cache(token_based=True)
        deleted_team = self.deleted_team()
        self.write_entry(deleted_team)

        with patch.object(self.redis, "register_script", side_effect=ConnectionError("down")):
            assert cleanup_stale_expiry_tracking(self.config) == 0

        assert self.entry_state(deleted_team) == (False, False, True)
        score = self.redis.zscore(self.sorted_set_key, deleted_team.api_token)
        assert score is not None and score > time.time() + 24 * 3600

        assert cleanup_stale_expiry_tracking(self.config) == 1
        assert self.entry_state(deleted_team) == (False, False, False)

    def test_an_entry_whose_delete_keeps_failing_does_not_starve_live_refreshes(self) -> None:
        self.given_cache(token_based=True)
        deleted_team = self.deleted_team()
        self.write_entry(self.team)
        self.write_entry(deleted_team)
        now = time.time()
        self.redis.zadd(self.sorted_set_key, {self.team.api_token: now + 3600, deleted_team.api_token: now + 60})
        failing_key = self.hypercache.get_cache_key(deleted_team)
        real_delete = self.hypercache.cache_client.delete

        def fail_for_deleted_team(key, *args, **kwargs):
            if key == failing_key:
                raise ConnectionError("down")
            return real_delete(key, *args, **kwargs)

        with patch.object(self.hypercache.cache_client, "delete", side_effect=fail_for_deleted_team):
            assert cleanup_stale_expiry_tracking(self.config) == 0

        assert select_expiring_teams(self.config, ttl_threshold_hours=24, limit=1).teams == [self.team]
