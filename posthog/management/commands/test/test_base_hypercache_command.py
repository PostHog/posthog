"""
Tests for BaseHyperCacheCommand error handling.

Tests cover:
- Graceful handling of Redis timeouts in get_cache_stats()
- Error counting when verify_team() raises exceptions
- Error reporting in verification results
- Continued processing after individual team errors
"""

from io import StringIO
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from redis.exceptions import TimeoutError as RedisTimeoutError

from posthog.management.commands._base_hypercache_command import BaseHyperCacheCommand
from posthog.storage.hypercache_manager import HyperCacheManagementConfig


class ConcreteHyperCacheCommand(BaseHyperCacheCommand):
    """Concrete implementation for testing the abstract base class."""

    def __init__(self, mock_config=None, verify_team_side_effect=None):
        super().__init__()
        self._mock_config = mock_config or MagicMock(spec=HyperCacheManagementConfig)
        self._verify_team_side_effect = verify_team_side_effect
        self._verify_team_call_count = 0

    def get_hypercache_config(self):
        return self._mock_config

    def verify_team(self, team, verbose, batch_data=None):
        self._verify_team_call_count += 1
        if self._verify_team_side_effect:
            if callable(self._verify_team_side_effect):
                return self._verify_team_side_effect(team)
            raise self._verify_team_side_effect
        return {"status": "match", "issue": None, "details": None}


@override_settings(FLAGS_REDIS_URL="redis://test", TEST=True)
class TestUpdateCacheStatsSafe(BaseTest):
    """Test _update_cache_stats_safe error handling."""

    def test_successful_cache_stats_update(self):
        """Test that _update_cache_stats_safe calls get_cache_stats successfully."""
        mock_config = MagicMock(spec=HyperCacheManagementConfig)
        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        with patch("posthog.management.commands._base_hypercache_command.get_cache_stats") as mock_get_cache_stats:
            mock_get_cache_stats.return_value = {"total_keys": 100}

            command._update_cache_stats_safe()

            mock_get_cache_stats.assert_called_once_with(mock_config)
            assert "Failed to update cache metrics" not in command.stdout.getvalue()

    @parameterized.expand(
        [
            ("redis_timeout", RedisTimeoutError("Connection timed out")),
            ("connection_error", ConnectionError("Redis unavailable")),
            ("generic_exception", Exception("Unexpected error")),
        ]
    )
    def test_handles_exception_gracefully(self, name, exception):
        """Test that _update_cache_stats_safe catches exceptions and logs warning."""
        mock_config = MagicMock(spec=HyperCacheManagementConfig)
        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        with patch("posthog.management.commands._base_hypercache_command.get_cache_stats") as mock_get_cache_stats:
            mock_get_cache_stats.side_effect = exception

            # Should not raise
            command._update_cache_stats_safe()

            output = command.stdout.getvalue()
            assert "Failed to update cache metrics" in output
            assert str(exception) in output

    def test_uses_provided_config(self):
        """Test that _update_cache_stats_safe uses provided config."""
        mock_config = MagicMock(spec=HyperCacheManagementConfig)
        other_config = MagicMock(spec=HyperCacheManagementConfig)
        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        with patch("posthog.management.commands._base_hypercache_command.get_cache_stats") as mock_get_cache_stats:
            command._update_cache_stats_safe(other_config)

            mock_get_cache_stats.assert_called_once_with(other_config)

    def test_uses_default_config_when_none_provided(self):
        """Test that _update_cache_stats_safe uses get_hypercache_config() when no config provided."""
        mock_config = MagicMock(spec=HyperCacheManagementConfig)
        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        with patch("posthog.management.commands._base_hypercache_command.get_cache_stats") as mock_get_cache_stats:
            command._update_cache_stats_safe()

            mock_get_cache_stats.assert_called_once_with(mock_config)


def create_mock_config():
    """Create a properly structured mock config for testing."""
    mock_config = MagicMock()
    mock_config.hypercache.batch_load_fn = None
    mock_config.hypercache.expiry_sorted_set_key = None  # Disable expiry tracking by default
    mock_config.cache_display_name = "test cache"
    return mock_config


@override_settings(FLAGS_REDIS_URL="redis://test", TEST=True)
class TestVerifyTeamErrorHandling(BaseTest):
    """Test error handling when verify_team() raises exceptions."""

    def test_verify_team_exception_increments_error_count(self):
        """Test that exceptions during team verification are counted as errors."""
        mock_config = create_mock_config()

        command = ConcreteHyperCacheCommand(
            mock_config=mock_config,
            verify_team_side_effect=RedisTimeoutError("Connection timed out"),
        )
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {
            "total": 0,
            "cache_miss": 0,
            "cache_match": 0,
            "cache_mismatch": 0,
            "expiry_missing": 0,
            "error": 0,
            "fixed": 0,
            "fix_failed": 0,
        }
        mismatches: list[dict[str, Any]] = []

        command._verify_teams_batch([self.team], stats, mismatches, verbose=False, fix=False)

        assert stats["error"] == 1
        assert stats["total"] == 1
        output = command.stdout.getvalue()
        assert f"Error verifying team {self.team.id}" in output

    def test_verify_team_exception_continues_to_next_team(self):
        """Test that after an exception, processing continues to the next team."""
        mock_config = create_mock_config()

        # First team raises, second team succeeds
        call_count = [0]

        def verify_side_effect(team):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RedisTimeoutError("Timeout on first team")
            return {"status": "match", "issue": None, "details": None}

        command = ConcreteHyperCacheCommand(
            mock_config=mock_config,
            verify_team_side_effect=verify_side_effect,
        )
        command.stdout = StringIO()  # type: ignore[assignment]

        # Create a second team
        from posthog.models import Team

        team2 = Team.objects.create(organization=self.organization, name="Team 2")

        stats = {
            "total": 0,
            "cache_miss": 0,
            "cache_match": 0,
            "cache_mismatch": 0,
            "expiry_missing": 0,
            "error": 0,
            "fixed": 0,
            "fix_failed": 0,
        }
        mismatches: list[dict[str, Any]] = []

        command._verify_teams_batch([self.team, team2], stats, mismatches, verbose=False, fix=False)

        assert stats["error"] == 1
        assert stats["cache_match"] == 1
        assert stats["total"] == 2
        assert command._verify_team_call_count == 2

    def test_all_teams_fail_verification(self):
        """Test handling when all teams fail verification."""
        mock_config = create_mock_config()

        command = ConcreteHyperCacheCommand(
            mock_config=mock_config,
            verify_team_side_effect=ConnectionError("Redis unavailable"),
        )
        command.stdout = StringIO()  # type: ignore[assignment]

        from posthog.models import Team

        team2 = Team.objects.create(organization=self.organization, name="Team 2")

        stats = {
            "total": 0,
            "cache_miss": 0,
            "cache_match": 0,
            "cache_mismatch": 0,
            "expiry_missing": 0,
            "error": 0,
            "fixed": 0,
            "fix_failed": 0,
        }
        mismatches: list[dict[str, Any]] = []

        command._verify_teams_batch([self.team, team2], stats, mismatches, verbose=False, fix=False)

        assert stats["error"] == 2
        assert stats["total"] == 2
        assert stats["cache_match"] == 0


@override_settings(FLAGS_REDIS_URL="redis://test", TEST=True)
class TestVerificationResultsErrorReporting(BaseTest):
    """Test error reporting in verification results."""

    def test_error_count_displayed_when_errors_occurred(self):
        """Test that error count is shown in results when errors > 0."""
        mock_config = MagicMock(spec=HyperCacheManagementConfig)
        mock_config.cache_display_name = "test cache"

        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {
            "total": 10,
            "cache_miss": 0,
            "cache_match": 8,
            "cache_mismatch": 0,
            "error": 2,
            "fixed": 0,
            "fix_failed": 0,
        }

        command._print_verification_results(stats, mismatches=[], verbose=False, fix=False)

        output = command.stdout.getvalue()
        assert "Errors:" in output
        assert "2" in output
        assert "20.0%" in output

    def test_error_count_not_displayed_when_no_errors(self):
        """Test that error line is omitted when no errors occurred."""
        mock_config = MagicMock(spec=HyperCacheManagementConfig)
        mock_config.cache_display_name = "test cache"

        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {
            "total": 10,
            "cache_miss": 0,
            "cache_match": 10,
            "cache_mismatch": 0,
            "error": 0,
            "fixed": 0,
            "fix_failed": 0,
        }

        command._print_verification_results(stats, mismatches=[], verbose=False, fix=False)

        output = command.stdout.getvalue()
        assert "Errors:" not in output

    def test_incomplete_verification_message_when_errors_with_issues(self):
        """Test that 'Verification incomplete' is shown when errors occurred with issues."""
        mock_config = MagicMock(spec=HyperCacheManagementConfig)
        mock_config.cache_display_name = "test cache"

        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {
            "total": 10,
            "cache_miss": 1,
            "cache_match": 7,
            "cache_mismatch": 0,
            "error": 2,
            "fixed": 0,
            "fix_failed": 0,
        }
        mismatches = [{"team_id": 1, "team_name": "Test", "issue": "MISS", "details": "test"}]

        command._print_verification_results(stats, mismatches=mismatches, verbose=False, fix=False)

        output = command.stdout.getvalue()
        assert "Verification incomplete" in output
        assert "2 error(s) occurred" in output

    def test_warning_message_when_issues_but_no_errors(self):
        """Test that warning message is shown when issues found but no errors."""
        mock_config = MagicMock(spec=HyperCacheManagementConfig)
        mock_config.cache_display_name = "test cache"

        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {
            "total": 10,
            "cache_miss": 1,
            "cache_match": 9,
            "cache_mismatch": 0,
            "error": 0,
            "fixed": 0,
            "fix_failed": 0,
        }
        mismatches = [{"team_id": 1, "team_name": "Test", "issue": "MISS", "details": "test"}]

        command._print_verification_results(stats, mismatches=mismatches, verbose=False, fix=False)

        output = command.stdout.getvalue()
        assert "Found issues with" in output
        assert "Verification incomplete" not in output


@override_settings(FLAGS_REDIS_URL="redis://test", TEST=True)
class TestRunVerificationErrorHandling(BaseTest):
    """Test run_verification handles get_cache_stats failures in finally block."""

    def test_run_verification_handles_cache_stats_failure(self):
        """Test that run_verification completes even if get_cache_stats fails in finally."""
        mock_config = create_mock_config()

        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        with patch("posthog.management.commands._base_hypercache_command.get_cache_stats") as mock_get_cache_stats:
            mock_get_cache_stats.side_effect = RedisTimeoutError("Connection timed out")

            # Should not raise - verification should complete
            command.run_verification(
                team_ids=[self.team.id],
                sample_size=None,
                verbose=False,
                fix=False,
            )

            output = command.stdout.getvalue()
            assert "Failed to update cache metrics" in output
            # Verification should still have completed
            assert "Verification Results" in output


def create_mock_config_with_expiry(expiry_sorted_set_key: str = "test_expiry_set"):
    """Create a mock config with expiry tracking enabled."""
    mock_config = MagicMock()
    mock_config.hypercache.batch_load_fn = None
    mock_config.hypercache.expiry_sorted_set_key = expiry_sorted_set_key
    mock_config.hypercache.redis_url = "redis://test"
    mock_config.hypercache.get_cache_identifier = lambda team: team.api_token
    mock_config.cache_display_name = "test cache"
    mock_config.update_fn = MagicMock(return_value=True)
    return mock_config


@override_settings(FLAGS_REDIS_URL="redis://test", TEST=True)
class TestExpiryTrackingVerification(BaseTest):
    """Test expiry tracking verification functionality."""

    def test_batch_check_expiry_returns_all_true_when_no_expiry_key_configured(self):
        """Test that batch_check_expiry_tracking returns all True when expiry tracking is disabled."""
        from posthog.storage.hypercache_manager import batch_check_expiry_tracking

        mock_config = create_mock_config()  # No expiry_sorted_set_key

        result = batch_check_expiry_tracking([self.team], mock_config)

        # All teams should be considered "tracked" when expiry tracking is disabled
        assert len(result) == 1
        assert all(v is True for v in result.values())

    def test_batch_check_expiry_uses_pipelining(self):
        """Test that batch_check_expiry_tracking uses Redis pipelining."""
        from posthog.storage.hypercache_manager import batch_check_expiry_tracking

        mock_config = create_mock_config_with_expiry()

        with patch("posthog.storage.hypercache_manager.get_client") as mock_get_client:
            mock_redis = MagicMock()
            mock_pipeline = MagicMock()
            mock_pipeline.execute.return_value = [1234567890.0]  # Score indicates team is tracked
            mock_redis.pipeline.return_value = mock_pipeline
            mock_get_client.return_value = mock_redis

            result = batch_check_expiry_tracking([self.team], mock_config)

            # Pipeline should have been created and executed
            mock_redis.pipeline.assert_called_once_with(transaction=False)
            mock_pipeline.zscore.assert_called_once()
            mock_pipeline.execute.assert_called_once()

            # Team should be marked as tracked (score was not None)
            assert result[self.team.api_token] is True

    def test_batch_check_expiry_returns_false_for_missing_teams(self):
        """Test that batch_check_expiry_tracking returns False for teams not in sorted set."""
        from posthog.storage.hypercache_manager import batch_check_expiry_tracking

        mock_config = create_mock_config_with_expiry()

        with patch("posthog.storage.hypercache_manager.get_client") as mock_get_client:
            mock_redis = MagicMock()
            mock_pipeline = MagicMock()
            mock_pipeline.execute.return_value = [None]  # None indicates team is not tracked
            mock_redis.pipeline.return_value = mock_pipeline
            mock_get_client.return_value = mock_redis

            result = batch_check_expiry_tracking([self.team], mock_config)

            # Team should be marked as NOT tracked (score was None)
            assert result[self.team.api_token] is False

    def test_expiry_missing_incremented_when_team_not_in_sorted_set(self):
        """Test that expiry_missing stat is incremented when team is not in expiry sorted set."""
        mock_config = create_mock_config_with_expiry()

        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {
            "total": 0,
            "cache_miss": 0,
            "cache_match": 0,
            "cache_mismatch": 0,
            "expiry_missing": 0,
            "error": 0,
            "fixed": 0,
            "fix_failed": 0,
        }
        mismatches: list[dict[str, Any]] = []

        with patch("posthog.storage.hypercache_manager.get_client") as mock_get_client:
            mock_redis = MagicMock()
            mock_pipeline = MagicMock()
            mock_pipeline.execute.return_value = [None]  # Team not in sorted set
            mock_redis.pipeline.return_value = mock_pipeline
            mock_get_client.return_value = mock_redis

            command._verify_teams_batch([self.team], stats, mismatches, verbose=False, fix=False)

        assert stats["cache_match"] == 1  # Cache data is valid
        assert stats["expiry_missing"] == 1  # But expiry tracking is missing
        assert len(mismatches) == 1
        assert mismatches[0]["issue"] == "EXPIRY_MISSING"

    def test_expiry_missing_not_incremented_when_team_in_sorted_set(self):
        """Test that expiry_missing is not incremented when team is properly tracked."""
        mock_config = create_mock_config_with_expiry()

        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {
            "total": 0,
            "cache_miss": 0,
            "cache_match": 0,
            "cache_mismatch": 0,
            "expiry_missing": 0,
            "error": 0,
            "fixed": 0,
            "fix_failed": 0,
        }
        mismatches: list[dict[str, Any]] = []

        with patch("posthog.storage.hypercache_manager.get_client") as mock_get_client:
            mock_redis = MagicMock()
            mock_pipeline = MagicMock()
            mock_pipeline.execute.return_value = [1234567890.0]  # Team is tracked
            mock_redis.pipeline.return_value = mock_pipeline
            mock_get_client.return_value = mock_redis

            command._verify_teams_batch([self.team], stats, mismatches, verbose=False, fix=False)

        assert stats["cache_match"] == 1
        assert stats["expiry_missing"] == 0
        assert len(mismatches) == 0

    def test_fix_team_cache_calls_update_fn(self):
        """Test that _fix_team_cache calls the update_fn to refresh cache and track expiry."""
        mock_config = create_mock_config_with_expiry()

        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {"fixed": 0, "fix_failed": 0}

        result = command._fix_team_cache(self.team, stats, "expiry tracking", mock_config)

        assert result is True
        assert stats["fixed"] == 1
        mock_config.update_fn.assert_called_once_with(self.team)

    def test_fix_team_cache_handles_update_fn_failure(self):
        """Test that _fix_team_cache handles update_fn returning False."""
        mock_config = create_mock_config_with_expiry()
        mock_config.update_fn.return_value = False

        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {"fixed": 0, "fix_failed": 0}

        result = command._fix_team_cache(self.team, stats, "expiry tracking", mock_config)

        assert result is False
        assert stats["fix_failed"] == 1

    def test_fix_team_cache_handles_exception(self):
        """Test that _fix_team_cache handles exceptions from update_fn."""
        mock_config = create_mock_config_with_expiry()
        mock_config.update_fn.side_effect = Exception("Redis error")

        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {"fixed": 0, "fix_failed": 0}

        result = command._fix_team_cache(self.team, stats, "expiry tracking", mock_config)

        assert result is False
        assert stats["fix_failed"] == 1

    def test_expiry_check_failure_continues_verification(self):
        """Test that failure in expiry check doesn't stop verification."""
        mock_config = create_mock_config_with_expiry()

        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {
            "total": 0,
            "cache_miss": 0,
            "cache_match": 0,
            "cache_mismatch": 0,
            "expiry_missing": 0,
            "error": 0,
            "fixed": 0,
            "fix_failed": 0,
        }
        mismatches: list[dict[str, Any]] = []

        with patch("posthog.storage.hypercache_manager.get_client") as mock_get_client:
            mock_get_client.side_effect = ConnectionError("Redis unavailable")

            command._verify_teams_batch([self.team], stats, mismatches, verbose=False, fix=False)

        # Verification should still have completed
        assert stats["cache_match"] == 1
        assert stats["expiry_missing"] == 0  # Expiry check was skipped
        output = command.stdout.getvalue()
        assert "Expiry tracking check failed" in output

    def test_print_verification_results_shows_expiry_missing(self):
        """Test that verification results include expiry_missing count."""
        mock_config = MagicMock(spec=HyperCacheManagementConfig)
        mock_config.cache_display_name = "test cache"

        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {
            "total": 10,
            "cache_miss": 0,
            "cache_match": 10,
            "cache_mismatch": 0,
            "expiry_missing": 3,
            "error": 0,
            "fixed": 0,
            "fix_failed": 0,
        }

        command._print_verification_results(stats, mismatches=[], verbose=False, fix=False)

        output = command.stdout.getvalue()
        assert "Expiry missing:" in output
        assert "3" in output
        assert "30.0%" in output

    def test_verification_success_requires_no_expiry_missing(self):
        """Test that verification only shows success when expiry_missing is 0."""
        mock_config = MagicMock(spec=HyperCacheManagementConfig)
        mock_config.cache_display_name = "test cache"

        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        # All caches match, but some have expiry issues
        stats = {
            "total": 10,
            "cache_miss": 0,
            "cache_match": 10,
            "cache_mismatch": 0,
            "expiry_missing": 2,
            "error": 0,
            "fixed": 0,
            "fix_failed": 0,
        }
        mismatches = [
            {"team_id": 1, "team_name": "Test1", "issue": "EXPIRY_MISSING", "details": "test"},
            {"team_id": 2, "team_name": "Test2", "issue": "EXPIRY_MISSING", "details": "test"},
        ]

        command._print_verification_results(stats, mismatches=mismatches, verbose=False, fix=False)

        output = command.stdout.getvalue()
        # Should NOT show success message
        assert "All test cache caches verified successfully" not in output
        # Should show issues found
        assert "Found issues" in output


@override_settings(FLAGS_REDIS_URL="redis://test", TEST=True)
class TestGracePeriodSkipping(BaseTest):
    """Test grace period skip functionality in management commands."""

    def test_skips_fix_when_team_in_grace_period(self):
        """Test that fix is skipped for teams within grace period."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.expiry_sorted_set_key = None
        mock_config.hypercache.get_cache_identifier = lambda team: team.id
        mock_config.get_team_ids_to_skip_fix_fn = lambda team_ids: {self.team.id}
        mock_config.cache_display_name = "test cache"

        # Return a mismatch to trigger fix attempt
        command = ConcreteHyperCacheCommand(
            mock_config=mock_config,
            verify_team_side_effect=lambda team: {
                "status": "mismatch",
                "issue": "DATA_MISMATCH",
                "details": "test mismatch",
            },
        )
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {
            "total": 0,
            "cache_miss": 0,
            "cache_match": 0,
            "cache_mismatch": 0,
            "expiry_missing": 0,
            "error": 0,
            "fixed": 0,
            "fix_failed": 0,
            "skipped_for_grace_period": 0,
        }
        mismatches: list[dict[str, Any]] = []

        command._verify_teams_batch([self.team], stats, mismatches, verbose=False, fix=True)

        assert stats["skipped_for_grace_period"] == 1
        assert stats["fixed"] == 0
        assert len(mismatches) == 1
        assert mismatches[0].get("skipped") is True
        assert "Skipped fix" in command.stdout.getvalue()

    def test_does_not_skip_when_team_not_in_grace_period(self):
        """Test that fix proceeds for teams not in grace period."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.expiry_sorted_set_key = None
        mock_config.hypercache.get_cache_identifier = lambda team: team.id
        mock_config.get_team_ids_to_skip_fix_fn = lambda team_ids: set()  # Empty - no skips
        mock_config.update_fn = MagicMock(return_value=True)
        mock_config.cache_display_name = "test cache"

        command = ConcreteHyperCacheCommand(
            mock_config=mock_config,
            verify_team_side_effect=lambda team: {
                "status": "mismatch",
                "issue": "DATA_MISMATCH",
                "details": "test mismatch",
            },
        )
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {
            "total": 0,
            "cache_miss": 0,
            "cache_match": 0,
            "cache_mismatch": 0,
            "expiry_missing": 0,
            "error": 0,
            "fixed": 0,
            "fix_failed": 0,
            "skipped_for_grace_period": 0,
        }
        mismatches: list[dict[str, Any]] = []

        command._verify_teams_batch([self.team], stats, mismatches, verbose=False, fix=True)

        assert stats["skipped_for_grace_period"] == 0
        assert stats["fixed"] == 1
        assert len(mismatches) == 1
        assert mismatches[0].get("fixed") is True
        mock_config.update_fn.assert_called_once()

    def test_skip_check_not_called_when_fix_is_false(self):
        """Test that skip check is not performed when fix=False."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.expiry_sorted_set_key = None
        mock_config.hypercache.get_cache_identifier = lambda team: team.id
        mock_config.get_team_ids_to_skip_fix_fn = MagicMock(return_value={self.team.id})
        mock_config.cache_display_name = "test cache"

        command = ConcreteHyperCacheCommand(
            mock_config=mock_config,
            verify_team_side_effect=lambda team: {
                "status": "mismatch",
                "issue": "DATA_MISMATCH",
                "details": "test mismatch",
            },
        )
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {
            "total": 0,
            "cache_miss": 0,
            "cache_match": 0,
            "cache_mismatch": 0,
            "expiry_missing": 0,
            "error": 0,
            "fixed": 0,
            "fix_failed": 0,
            "skipped_for_grace_period": 0,
        }
        mismatches: list[dict[str, Any]] = []

        command._verify_teams_batch([self.team], stats, mismatches, verbose=False, fix=False)

        # Skip function should NOT be called when fix=False
        mock_config.get_team_ids_to_skip_fix_fn.assert_not_called()

    def test_skip_check_handles_exception_gracefully(self):
        """Test that skip check failures don't stop verification."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.expiry_sorted_set_key = None
        mock_config.hypercache.get_cache_identifier = lambda team: team.id
        mock_config.get_team_ids_to_skip_fix_fn = MagicMock(side_effect=Exception("DB error"))
        mock_config.update_fn = MagicMock(return_value=True)
        mock_config.cache_display_name = "test cache"

        command = ConcreteHyperCacheCommand(
            mock_config=mock_config,
            verify_team_side_effect=lambda team: {
                "status": "mismatch",
                "issue": "DATA_MISMATCH",
                "details": "test mismatch",
            },
        )
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {
            "total": 0,
            "cache_miss": 0,
            "cache_match": 0,
            "cache_mismatch": 0,
            "expiry_missing": 0,
            "error": 0,
            "fixed": 0,
            "fix_failed": 0,
            "skipped_for_grace_period": 0,
        }
        mismatches: list[dict[str, Any]] = []

        command._verify_teams_batch([self.team], stats, mismatches, verbose=False, fix=True)

        # Should proceed with fix since skip check failed
        assert stats["fixed"] == 1
        assert "Skip-fix check failed" in command.stdout.getvalue()

    def test_print_results_shows_skipped_count(self):
        """Test that skipped count is shown in verification results."""
        mock_config = MagicMock(spec=HyperCacheManagementConfig)
        mock_config.cache_display_name = "test cache"

        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {
            "total": 10,
            "cache_miss": 1,
            "cache_match": 8,
            "cache_mismatch": 1,
            "expiry_missing": 0,
            "error": 0,
            "fixed": 0,
            "fix_failed": 0,
            "skipped_for_grace_period": 2,
        }
        mismatches = [
            {"team_id": 1, "team_name": "Test1", "issue": "MISMATCH", "details": "test", "skipped": True},
            {"team_id": 2, "team_name": "Test2", "issue": "MISMATCH", "details": "test", "skipped": True},
        ]

        command._print_verification_results(stats, mismatches=mismatches, verbose=False, fix=True)

        output = command.stdout.getvalue()
        assert "Skipped (grace period):" in output
        assert "2" in output
        assert "SKIPPED (grace period)" in output

    def test_print_results_hides_skipped_when_zero(self):
        """Test that skipped line is omitted when no teams were skipped."""
        mock_config = MagicMock(spec=HyperCacheManagementConfig)
        mock_config.cache_display_name = "test cache"

        command = ConcreteHyperCacheCommand(mock_config=mock_config)
        command.stdout = StringIO()  # type: ignore[assignment]

        stats = {
            "total": 10,
            "cache_miss": 0,
            "cache_match": 10,
            "cache_mismatch": 0,
            "expiry_missing": 0,
            "error": 0,
            "fixed": 0,
            "fix_failed": 0,
            "skipped_for_grace_period": 0,
        }

        command._print_verification_results(stats, mismatches=[], verbose=False, fix=True)

        output = command.stdout.getvalue()
        assert "Skipped (grace period)" not in output
