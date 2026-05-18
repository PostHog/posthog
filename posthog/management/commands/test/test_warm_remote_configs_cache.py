from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.models.project import Project
from posthog.models.remote_config import RemoteConfig


class TestWarmRemoteConfigsCache(BaseTest):
    """
    Tests for the warm_remote_configs_cache management command.

    The hypercache writes to whichever cache `RemoteConfig.get_hypercache().cache_client`
    resolves to — that's the dedicated flags cache when FLAGS_REDIS_URL is configured
    (the test environment sets it) and the default cache otherwise. Tests read back
    through the same cache_client so they exercise whichever backend prod would use.
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
        assert "skipped_empty=1" in out.getvalue()
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

        call_command("warm_remote_configs_cache", team_ids=[self.team.id], stdout=StringIO())

        assert self._cached_value(self.team.api_token) is not None
        assert self._cached_value(other_team.api_token) is None

    def test_invalid_batch_size_raises(self):
        with self.assertRaisesMessage(CommandError, "--batch-size"):
            call_command("warm_remote_configs_cache", batch_size=0, stdout=StringIO())

        with self.assertRaisesMessage(CommandError, "--batch-size"):
            call_command("warm_remote_configs_cache", batch_size=20_000, stdout=StringIO())

    def test_failed_writes_raise_command_error(self):
        with patch(
            "posthog.storage.hypercache.HyperCache._set_cache_value_redis",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaisesMessage(CommandError, "row(s) failed to warm"):
                call_command("warm_remote_configs_cache", stdout=StringIO())

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
