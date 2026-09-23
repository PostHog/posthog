import time

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.team.team import Team
from posthog.storage.cache_expiry_manager import ExpiringTeamSelection, RefreshPacing, refresh_expiring_caches
from posthog.storage.test.test_hypercache_manager import create_test_config as build_config

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
