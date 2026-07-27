from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from parameterized import parameterized

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS
from posthog.models.project import Project
from posthog.models.remote_config import RemoteConfig


@override_settings(
    CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        FLAGS_DEDICATED_CACHE_ALIAS: {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "redis://stub:6379/",
        },
    }
)
class TestWarmRemoteConfigsCache(BaseTest):
    """
    Tests for the warm_remote_configs_cache management command.

    In CI, `FLAGS_REDIS_URL` is unset, so `RemoteConfig.get_hypercache().cache_client`
    resolves to the default LocMemCache. The roundtrip assertions in
    `test_remote_config.py` cover the dedicated-alias path under `override_settings`.

    These tests register the dedicated alias via `override_settings` so the
    command's fail-fast guard passes and exercise the writer path the dedicated
    alias selects.
    """

    def setUp(self):
        super().setUp()
        self.hypercache = RemoteConfig.get_hypercache()
        # Drop any prior state so each test starts from a known cache and DB shape.
        self.hypercache.cache_client.clear()
        RemoteConfig.objects.filter(team=self.team).delete()
        self.remote_config = RemoteConfig.objects.create(
            team=self.team,
            config={"token": self.team.api_token, "hasFeatureFlags": False},
        )

    def _cached_value(self, api_token: str):
        return self.hypercache.cache_client.get(self.hypercache.get_cache_key(api_token))

    def test_warms_redis_cache_for_persisted_config_rows(self):
        out = StringIO()
        call_command("warm_remote_configs_cache", stdout=out)

        cached = self._cached_value(self.team.api_token)
        assert cached is not None
        assert self.team.api_token in cached
        assert "warmed=1" in out.getvalue()
        assert "failed=0" in out.getvalue()

    def test_skips_teams_with_empty_config(self):
        self.remote_config.config = {}
        self.remote_config.save(update_fields=["config"])

        out = StringIO()
        call_command("warm_remote_configs_cache", stdout=out)

        assert self._cached_value(self.team.api_token) is None
        assert "Backfilling 0 RemoteConfig row(s)" in out.getvalue()
        assert "warmed=0" in out.getvalue()

    def test_dry_run_does_not_write_to_cache(self):
        out = StringIO()
        call_command("warm_remote_configs_cache", dry_run=True, stdout=out)

        assert self._cached_value(self.team.api_token) is None
        assert "(dry run)" in out.getvalue()

    def test_team_ids_filters_backfill(self):
        _, other_team = Project.objects.create_with_team(
            initiating_user=self.user, organization=self.organization, name="Other"
        )
        RemoteConfig.objects.filter(team=other_team).delete()
        RemoteConfig.objects.create(team=other_team, config={"token": other_team.api_token})
        # Make "other_team has no cache entry" an explicit precondition rather than
        # relying on TestCase swallowing the post_save on_commit hook.
        self.hypercache.cache_client.delete(self.hypercache.get_cache_key(other_team.api_token))

        call_command("warm_remote_configs_cache", team_ids=[self.team.id], stdout=StringIO())

        assert self._cached_value(self.team.api_token) is not None
        assert self._cached_value(other_team.api_token) is None

    @parameterized.expand(
        [
            ("zero", 0),
            ("over_max", 20_000),
        ]
    )
    def test_invalid_batch_size_raises(self, _name, batch_size):
        with self.assertRaisesMessage(CommandError, "--batch-size"):
            call_command("warm_remote_configs_cache", batch_size=batch_size, stdout=StringIO())

    def test_failed_writes_raise_command_error(self):
        with patch(
            "posthog.storage.hypercache.HyperCache._set_cache_value_redis",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaisesMessage(CommandError, "row(s) failed to warm"):
                call_command("warm_remote_configs_cache", stdout=StringIO())

    @patch("posthog.storage.hypercache.get_client")
    def test_warm_seeds_expiry_tracking(self, mock_get_client):
        # The warm seeds the remote_config_cache_expiry sorted set the hourly refresh reads.
        from posthog.models.remote_config import REMOTE_CONFIG_CACHE_EXPIRY_SORTED_SET

        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        call_command("warm_remote_configs_cache", stdout=StringIO())

        mock_redis.zadd.assert_called()
        sorted_set_key, member_map = mock_redis.zadd.call_args[0]
        assert sorted_set_key == REMOTE_CONFIG_CACHE_EXPIRY_SORTED_SET
        assert self.team.api_token in member_map

    def test_does_not_write_to_s3(self):
        # Regression guard: the warm path must be Redis-only. Writing to S3 per
        # row would dominate runtime at the scale this command is built for
        # (tens of thousands of teams). The Redis tier is what the Rust service
        # reads first; S3 is already populated via the normal sync() path.
        with patch("posthog.storage.object_storage.write") as mock_s3_write:
            call_command("warm_remote_configs_cache", stdout=StringIO())

        mock_s3_write.assert_not_called()
        # Sanity: cache was populated
        assert self._cached_value(self.team.api_token) is not None

    def test_raises_when_dedicated_cache_not_configured(self):
        with override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}):
            with self.assertRaisesMessage(CommandError, "FLAGS_REDIS_URL is not configured"):
                call_command("warm_remote_configs_cache", stdout=StringIO())
