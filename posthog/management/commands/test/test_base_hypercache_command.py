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
