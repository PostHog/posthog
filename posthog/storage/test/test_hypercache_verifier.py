"""
Tests for HyperCache verification utilities.

Tests cover:
- VerificationResult tracking and formatting
- verify_and_fix_all_teams batch processing
- Auto-fix for cache issues (miss, mismatch, expiry_missing)
- Error handling and edge cases
"""

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from parameterized import parameterized

from posthog.storage.hypercache_verifier import (
    MAX_FIXED_TEAM_IDS_TO_LOG,
    VerificationResult,
    _fix_and_record,
    _partition_teams_for_verification,
    _verify_and_fix_batch,
    _verify_empty_cache_team,
    verify_and_fix_all_teams,
)


class TestVerificationResult(TestCase):
    """Test VerificationResult dataclass functionality."""

    def test_default_values(self):
        """Test that VerificationResult has correct defaults."""
        result = VerificationResult()

        assert result.total == 0
        assert result.cache_miss_fixed == 0
        assert result.cache_mismatch_fixed == 0
        assert result.expiry_missing_fixed == 0
        assert result.fix_failed == 0
        assert result.errors == 0
        assert result.skipped_for_grace_period == 0
        assert result.fixed_team_ids == []
        assert result.skipped_team_ids == []

    def test_total_fixed_property(self):
        """Test that total_fixed sums all fix types."""
        result = VerificationResult(
            cache_miss_fixed=3,
            cache_mismatch_fixed=2,
            expiry_missing_fixed=5,
        )

        assert result.total_fixed == 10

    @parameterized.expand(
        [
            ("empty_list", [], "[]"),
            ("single_id", [123], "[123]"),
            ("few_ids", [1, 2, 3], "[1, 2, 3]"),
            ("exactly_max", list(range(1, 11)), str(list(range(1, 11)))),
        ]
    )
    def test_formatted_fixed_team_ids_no_truncation(self, name, team_ids, expected):
        """Test formatted_fixed_team_ids with lists that don't need truncation."""
        result = VerificationResult(fixed_team_ids=team_ids)
        assert result.formatted_fixed_team_ids() == expected

    def test_formatted_fixed_team_ids_truncates_beyond_max(self):
        """Test that formatted_fixed_team_ids truncates lists beyond MAX_FIXED_TEAM_IDS_TO_LOG."""
        team_ids = list(range(1, 16))  # 15 IDs
        result = VerificationResult(fixed_team_ids=team_ids)

        formatted = result.formatted_fixed_team_ids()

        # Should show first 10 and indicate 5 more
        expected_truncated = list(range(1, 11))
        assert formatted == f"{expected_truncated} ... and 5 more"

    def test_formatted_fixed_team_ids_large_list(self):
        """Test formatted_fixed_team_ids with a large list."""
        team_ids = list(range(1, 1001))  # 1000 IDs
        result = VerificationResult(fixed_team_ids=team_ids)

        formatted = result.formatted_fixed_team_ids()

        # Should show first 10 and indicate 990 more
        expected_truncated = list(range(1, 11))
        remaining = 1000 - MAX_FIXED_TEAM_IDS_TO_LOG
        assert formatted == f"{expected_truncated} ... and {remaining} more"

    @parameterized.expand(
        [
            ("empty_list", [], "[]"),
            ("single_id", [456], "[456]"),
            ("few_ids", [7, 8, 9], "[7, 8, 9]"),
            ("exactly_max", list(range(100, 110)), str(list(range(100, 110)))),
        ]
    )
    def test_formatted_skipped_team_ids_no_truncation(self, name, team_ids, expected):
        """Test formatted_skipped_team_ids with lists that don't need truncation."""
        result = VerificationResult(skipped_team_ids=team_ids)
        assert result.formatted_skipped_team_ids() == expected

    def test_formatted_skipped_team_ids_truncates_beyond_max(self):
        """Test that formatted_skipped_team_ids truncates lists beyond MAX_FIXED_TEAM_IDS_TO_LOG."""
        team_ids = list(range(100, 120))  # 20 IDs
        result = VerificationResult(skipped_team_ids=team_ids)

        formatted = result.formatted_skipped_team_ids()

        # Should show first 10 and indicate 10 more
        expected_truncated = list(range(100, 110))
        assert formatted == f"{expected_truncated} ... and 10 more"


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestFixAndRecord(BaseTest):
    """Test _fix_and_record helper function."""

    @parameterized.expand(
        [
            ("cache_miss", "cache_miss_fixed"),
            ("cache_mismatch", "cache_mismatch_fixed"),
            ("expiry_missing", "expiry_missing_fixed"),
        ]
    )
    def test_successful_fix_increments_correct_counter(self, issue_type, expected_counter):
        """Test that successful fix increments the correct counter for each issue type."""
        mock_config = MagicMock()
        mock_config.update_fn.return_value = True

        result = VerificationResult()

        _fix_and_record(
            team=self.team,
            config=mock_config,
            issue_type=issue_type,
            cache_type="test_cache",
            result=result,
        )

        # Only the expected counter should be incremented
        assert getattr(result, expected_counter) == 1
        assert result.fix_failed == 0
        assert self.team.id in result.fixed_team_ids
        # Other counters should be 0
        all_counters = ["cache_miss_fixed", "cache_mismatch_fixed", "expiry_missing_fixed"]
        for counter in all_counters:
            if counter != expected_counter:
                assert getattr(result, counter) == 0

    def test_failed_fix_increments_fix_failed(self):
        """Test that failed fix increments fix_failed counter."""
        mock_config = MagicMock()
        mock_config.update_fn.return_value = False

        result = VerificationResult()

        _fix_and_record(
            team=self.team,
            config=mock_config,
            issue_type="cache_miss",
            cache_type="test_cache",
            result=result,
        )

        assert result.cache_miss_fixed == 0
        assert result.fix_failed == 1
        assert self.team.id not in result.fixed_team_ids

    def test_exception_in_update_fn_increments_fix_failed(self):
        """Test that exception in update_fn increments fix_failed."""
        mock_config = MagicMock()
        mock_config.update_fn.side_effect = Exception("Update failed")

        result = VerificationResult()

        _fix_and_record(
            team=self.team,
            config=mock_config,
            issue_type="cache_miss",
            cache_type="test_cache",
            result=result,
        )

        assert result.cache_miss_fixed == 0
        assert result.fix_failed == 1


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyAndFixBatch(BaseTest):
    """Test _verify_and_fix_batch helper function."""

    def test_match_status_does_not_fix(self):
        """Test that cache match status doesn't trigger a fix."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.hypercache.get_cache_identifier.return_value = str(self.team.id)

        result = VerificationResult()

        def verify_fn(team, db_batch_data, cache_batch_data):
            return {"status": "match", "issue": None}

        with patch(
            "posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={str(self.team.id): True}
        ):
            _verify_and_fix_batch(
                teams=[self.team],
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                result=result,
            )

        assert result.total == 1
        assert result.total_fixed == 0
        mock_config.update_fn.assert_not_called()

    @parameterized.expand(
        [
            ("miss", "CACHE_MISS", "cache_miss_fixed"),
            ("mismatch", "DATA_MISMATCH", "cache_mismatch_fixed"),
        ]
    )
    def test_status_triggers_fix(self, status, issue, expected_counter):
        """Test that miss/mismatch status triggers the appropriate fix."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.update_fn.return_value = True
        mock_config.get_team_ids_to_skip_fix_fn = None

        result = VerificationResult()

        def verify_fn(team, db_batch_data, cache_batch_data):
            return {"status": status, "issue": issue}

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}):
            _verify_and_fix_batch(
                teams=[self.team],
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                result=result,
            )

        assert result.total == 1
        assert getattr(result, expected_counter) == 1
        # When db_batch_data is None (no batch_load_fn), it falls back to update_fn
        mock_config.update_fn.assert_called_once_with(self.team)

    def test_expiry_missing_triggers_fix_for_match_status(self):
        """Test that missing expiry tracking triggers fix even when cache matches."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.hypercache.get_cache_identifier.return_value = str(self.team.id)
        mock_config.update_fn.return_value = True
        mock_config.get_team_ids_to_skip_fix_fn = None

        result = VerificationResult()

        def verify_fn(team, db_batch_data, cache_batch_data):
            return {"status": "match", "issue": None}

        # Expiry status shows team is NOT tracked (False)
        with patch(
            "posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={str(self.team.id): False}
        ):
            _verify_and_fix_batch(
                teams=[self.team],
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                result=result,
            )

        assert result.total == 1
        assert result.expiry_missing_fixed == 1
        # When db_batch_data is None (no batch_load_fn), it falls back to update_fn
        mock_config.update_fn.assert_called_once_with(self.team)

    def test_verification_error_increments_errors(self):
        """Test that verification errors are counted."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}

        result = VerificationResult()

        def verify_fn(team, db_batch_data, cache_batch_data):
            raise Exception("Verification failed")

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}):
            _verify_and_fix_batch(
                teams=[self.team],
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                result=result,
            )

        assert result.total == 1
        assert result.errors == 1
        assert result.total_fixed == 0

    def test_batch_load_fn_called_when_available(self) -> None:
        mock_config = MagicMock()
        mock_db_batch_data: dict = {self.team.id: {"flags": []}}
        mock_config.hypercache.batch_load_fn.return_value = mock_db_batch_data
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.hypercache.get_cache_identifier.return_value = str(self.team.id)

        result = VerificationResult()
        received_db_batch_data = []

        def verify_fn(team, db_batch_data, cache_batch_data):
            received_db_batch_data.append(db_batch_data)
            return {"status": "match", "issue": None}

        with patch(
            "posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={str(self.team.id): True}
        ):
            _verify_and_fix_batch(
                teams=[self.team],
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                result=result,
            )

        mock_config.hypercache.batch_load_fn.assert_called_once_with([self.team])
        mock_config.hypercache.batch_get_from_cache.assert_called_once_with([self.team])
        assert received_db_batch_data[0] == mock_db_batch_data

    @parameterized.expand(
        [
            ("cache_miss", {"status": "miss", "issue": "CACHE_MISS"}, {}, "cache_miss_fixed"),
            ("cache_mismatch", {"status": "mismatch", "issue": "DATA_MISMATCH"}, {}, "cache_mismatch_fixed"),
        ]
    )
    def test_fix_uses_update_fn_for_dual_write(self, _name, verification_result, expiry_status, result_attr):
        """Test that fixes use update_fn to ensure dual-write to both shared and dedicated caches."""
        mock_config = MagicMock()
        mock_db_batch_data: dict = {self.team.id: {"flags": ["flag1", "flag2"]}}
        mock_config.hypercache.batch_load_fn.return_value = mock_db_batch_data
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.update_fn.return_value = True
        mock_config.get_team_ids_to_skip_fix_fn = None

        result = VerificationResult()

        def verify_fn(team, db_batch_data, cache_batch_data):
            return verification_result

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value=expiry_status):
            _verify_and_fix_batch(
                teams=[self.team],
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                result=result,
            )

        # Should call update_fn for dual-write (writes to both shared and dedicated caches)
        mock_config.update_fn.assert_called_once_with(self.team)
        assert getattr(result, result_attr) == 1

    def test_expiry_missing_fix_uses_update_fn_for_dual_write(self):
        """Test that expiry_missing fixes use update_fn to ensure dual-write to both caches."""
        mock_config = MagicMock()
        mock_db_batch_data: dict = {self.team.id: {"flags": ["flag1", "flag2"]}}
        mock_config.hypercache.batch_load_fn.return_value = mock_db_batch_data
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.hypercache.get_cache_identifier.return_value = str(self.team.id)
        mock_config.update_fn.return_value = True
        mock_config.get_team_ids_to_skip_fix_fn = None

        result = VerificationResult()

        def verify_fn(team, db_batch_data, cache_batch_data):
            # Return match - but expiry tracking will be missing
            return {"status": "match", "issue": None}

        # Expiry status shows this team is NOT tracked (False)
        expiry_status = {str(self.team.id): False}

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value=expiry_status):
            _verify_and_fix_batch(
                teams=[self.team],
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                result=result,
            )

        # Should call update_fn for dual-write (writes to both shared and dedicated caches)
        mock_config.update_fn.assert_called_once_with(self.team)
        assert result.expiry_missing_fixed == 1

    def test_fix_falls_back_to_update_fn_without_batch_load(self):
        """Test that fixes fall back to update_fn when batch_load_fn is not available."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.update_fn.return_value = True
        mock_config.get_team_ids_to_skip_fix_fn = None

        result = VerificationResult()

        def verify_fn(team, db_batch_data, cache_batch_data):
            return {"status": "miss", "issue": "CACHE_MISS"}

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}):
            _verify_and_fix_batch(
                teams=[self.team],
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                result=result,
            )

        # Should call update_fn, NOT set_cache_value
        mock_config.update_fn.assert_called_once_with(self.team)
        mock_config.hypercache.set_cache_value.assert_not_called()
        assert result.cache_miss_fixed == 1

    def test_batch_get_from_cache_error_falls_back_to_empty_dict(self):
        """Test that batch_get_from_cache errors fall back to empty dict (individual lookups)."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.side_effect = Exception("Redis connection failed")
        mock_config.hypercache.get_cache_identifier.return_value = str(self.team.id)

        result = VerificationResult()
        received_cache_batch_data = []

        def verify_fn(team, db_batch_data, cache_batch_data):
            received_cache_batch_data.append(cache_batch_data)
            return {"status": "match", "issue": None}

        with patch(
            "posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={str(self.team.id): True}
        ):
            _verify_and_fix_batch(
                teams=[self.team],
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                result=result,
            )

        # verify_fn should receive empty dict when batch_get_from_cache fails
        assert received_cache_batch_data[0] == {}
        assert result.total == 1
        assert result.errors == 0  # Should not count as error, just fallback

    def test_get_team_ids_to_skip_fix_fn_skips_fix_for_full_verification(self):
        """Test that get_team_ids_to_skip_fix_fn can skip fixes for teams with recent updates."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        # Return team ID in the skip set
        mock_config.get_team_ids_to_skip_fix_fn.return_value = {self.team.id}

        result = VerificationResult()

        def verify_fn(team, db_batch_data, cache_batch_data):
            return {"status": "miss", "issue": "CACHE_MISS"}

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}):
            _verify_and_fix_batch(
                teams=[self.team],
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                result=result,
            )

        # Fix should be skipped
        assert result.total == 1
        assert result.total_fixed == 0
        assert result.skipped_for_grace_period == 1
        assert self.team.id in result.skipped_team_ids
        mock_config.update_fn.assert_not_called()
        mock_config.hypercache.set_cache_value.assert_not_called()

    def test_get_team_ids_to_skip_fix_fn_none_does_not_skip(self):
        """Test that when get_team_ids_to_skip_fix_fn is None, fixes proceed normally."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.get_team_ids_to_skip_fix_fn = None  # No skip function
        mock_config.update_fn.return_value = True

        result = VerificationResult()

        def verify_fn(team, db_batch_data, cache_batch_data):
            return {"status": "miss", "issue": "CACHE_MISS"}

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}):
            _verify_and_fix_batch(
                teams=[self.team],
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                result=result,
            )

        # Fix should proceed
        assert result.total == 1
        assert result.cache_miss_fixed == 1
        assert result.skipped_for_grace_period == 0
        mock_config.update_fn.assert_called_once()

    def test_get_team_ids_to_skip_fix_fn_empty_set_does_not_skip(self):
        """Test that when get_team_ids_to_skip_fix_fn returns empty set, fixes proceed."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.get_team_ids_to_skip_fix_fn.return_value = set()  # Empty set - don't skip
        mock_config.update_fn.return_value = True

        result = VerificationResult()

        def verify_fn(team, db_batch_data, cache_batch_data):
            return {"status": "miss", "issue": "CACHE_MISS"}

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}):
            _verify_and_fix_batch(
                teams=[self.team],
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                result=result,
            )

        # Fix should proceed
        assert result.total == 1
        assert result.cache_miss_fixed == 1
        assert result.skipped_for_grace_period == 0


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyAndFixAllTeams(BaseTest):
    """Test verify_and_fix_all_teams function."""

    def test_processes_all_teams_in_chunks(self):
        """Test that all teams are processed in chunks."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.hypercache.get_cache_identifier.side_effect = lambda t: str(t.id)

        def verify_fn(team, db_batch_data, cache_batch_data):
            return {"status": "match", "issue": None}

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}):
            result = verify_and_fix_all_teams(
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                chunk_size=100,
            )

        # Should have processed at least self.team
        assert result.total >= 1

    def test_returns_aggregated_results(self):
        """Test that results are aggregated across all chunks."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.update_fn.return_value = True
        mock_config.get_team_ids_to_skip_fix_fn = None

        def verify_fn(team, db_batch_data, cache_batch_data):
            return {"status": "miss", "issue": "CACHE_MISS"}

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}):
            result = verify_and_fix_all_teams(
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                chunk_size=100,
            )

        # All teams should have been fixed (cache miss)
        assert result.total == result.cache_miss_fixed
        assert len(result.fixed_team_ids) == result.total


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestPartitionTeamsForVerification(BaseTest):
    """Test _partition_teams_for_verification helper function."""

    def test_all_teams_full_check_when_optimization_disabled(self):
        """When team_ids_needing_full_verification is None, all teams go to full check."""
        mock_config = MagicMock()
        mock_config.empty_cache_value = None

        teams = [self.team]
        full_check, empty_check = _partition_teams_for_verification(teams, None, mock_config)

        assert full_check == teams
        assert empty_check == []

    def test_all_teams_full_check_when_empty_cache_value_is_none(self):
        """When empty_cache_value is None, all teams go to full check even with team_ids set."""
        mock_config = MagicMock()
        mock_config.empty_cache_value = None

        teams = [self.team]
        team_ids = {self.team.id}
        full_check, empty_check = _partition_teams_for_verification(teams, team_ids, mock_config)

        assert full_check == teams
        assert empty_check == []

    def test_teams_with_flags_go_to_full_check(self):
        """Teams in team_ids_needing_full_verification go to full check."""
        mock_config = MagicMock()
        mock_config.empty_cache_value = {"flags": []}

        teams = [self.team]
        team_ids_with_flags = {self.team.id}
        full_check, empty_check = _partition_teams_for_verification(teams, team_ids_with_flags, mock_config)

        assert full_check == [self.team]
        assert empty_check == []

    def test_teams_without_flags_go_to_empty_check(self):
        """Teams NOT in team_ids_needing_full_verification go to empty check."""
        mock_config = MagicMock()
        mock_config.empty_cache_value = {"flags": []}

        teams = [self.team]
        team_ids_with_flags: set[int] = set()  # Empty - no teams have flags
        full_check, empty_check = _partition_teams_for_verification(teams, team_ids_with_flags, mock_config)

        assert full_check == []
        assert empty_check == [self.team]

    def test_mixed_teams_split_correctly(self):
        """Batch with mix of teams with/without flags splits correctly."""
        from posthog.models import Team

        team2 = Team.objects.create(organization=self.organization, name="Team 2")

        mock_config = MagicMock()
        mock_config.empty_cache_value = {"flags": []}

        teams = [self.team, team2]
        # Only self.team has flags
        team_ids_with_flags = {self.team.id}
        full_check, empty_check = _partition_teams_for_verification(teams, team_ids_with_flags, mock_config)

        assert full_check == [self.team]
        assert empty_check == [team2]


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyEmptyCacheTeam(BaseTest):
    """Test _verify_empty_cache_team fast-path verification."""

    def test_cache_miss_triggers_fix(self):
        """Teams with no cache entry should be fixed via update_fn for dual-write."""
        mock_config = MagicMock()
        mock_config.empty_cache_value = {"flags": []}
        mock_config.update_fn.return_value = True

        result = VerificationResult()
        # Cache batch data has no entry for this team (cache miss)
        cache_batch_data: dict = {}

        _verify_empty_cache_team(
            team=self.team,
            config=mock_config,
            cache_batch_data=cache_batch_data,
            expiry_status=None,
            cache_type="flags",
            result=result,
            team_ids_to_skip_fix=set(),
        )

        # Should trigger cache_miss fix via update_fn (dual-write to both caches)
        assert result.cache_miss_fixed == 1
        mock_config.update_fn.assert_called_once_with(self.team)

    def test_cached_data_none_triggers_fix(self):
        """Teams with cached_data=None should be fixed."""
        mock_config = MagicMock()
        mock_config.empty_cache_value = {"flags": []}

        result = VerificationResult()
        # Cache entry exists but data is None
        cache_batch_data = {self.team.id: (None, "redis")}

        _verify_empty_cache_team(
            team=self.team,
            config=mock_config,
            cache_batch_data=cache_batch_data,
            expiry_status=None,
            cache_type="flags",
            result=result,
            team_ids_to_skip_fix=set(),
        )

        assert result.cache_miss_fixed == 1

    def test_cache_mismatch_triggers_fix(self):
        """Teams with cached flags but expected empty should be fixed via update_fn."""
        mock_config = MagicMock()
        mock_config.empty_cache_value = {"flags": []}
        mock_config.update_fn.return_value = True

        result = VerificationResult()
        # Cache has stale data (team used to have flags)
        cache_batch_data = {self.team.id: ({"flags": [{"id": 1, "key": "old-flag"}]}, "redis")}

        _verify_empty_cache_team(
            team=self.team,
            config=mock_config,
            cache_batch_data=cache_batch_data,
            expiry_status=None,
            cache_type="flags",
            result=result,
            team_ids_to_skip_fix=set(),
        )

        # Should trigger cache_mismatch fix via update_fn (dual-write to both caches)
        assert result.cache_mismatch_fixed == 1
        mock_config.update_fn.assert_called_once_with(self.team)

    def test_cache_match_no_fix(self):
        """Teams with correct empty cache should not trigger fix."""
        mock_config = MagicMock()
        mock_config.empty_cache_value = {"flags": []}
        mock_config.hypercache.get_cache_identifier.return_value = str(self.team.id)

        result = VerificationResult()
        # Cache correctly has empty value
        cache_batch_data: dict = {self.team.id: ({"flags": []}, "redis")}
        expiry_status = {str(self.team.id): True}  # Tracked

        _verify_empty_cache_team(
            team=self.team,
            config=mock_config,
            cache_batch_data=cache_batch_data,
            expiry_status=expiry_status,
            cache_type="flags",
            result=result,
            team_ids_to_skip_fix=set(),
        )

        # No fixes should be triggered
        assert result.total_fixed == 0
        mock_config.hypercache.set_cache_value.assert_not_called()

    def test_expiry_missing_triggers_fix(self):
        """Empty cache match but missing expiry tracking should trigger fix."""
        mock_config = MagicMock()
        mock_config.empty_cache_value = {"flags": []}
        mock_config.hypercache.get_cache_identifier.return_value = str(self.team.id)

        result = VerificationResult()
        # Cache matches but expiry tracking missing
        cache_batch_data: dict = {self.team.id: ({"flags": []}, "redis")}
        expiry_status = {str(self.team.id): False}  # NOT tracked

        _verify_empty_cache_team(
            team=self.team,
            config=mock_config,
            cache_batch_data=cache_batch_data,
            expiry_status=expiry_status,
            cache_type="flags",
            result=result,
            team_ids_to_skip_fix=set(),
        )

        # Should fix expiry tracking
        assert result.expiry_missing_fixed == 1

    def test_raises_value_error_if_empty_cache_value_not_set(self):
        """Should raise ValueError if empty_cache_value is None."""
        mock_config = MagicMock()
        mock_config.empty_cache_value = None  # Misconfiguration

        result = VerificationResult()
        cache_batch_data: dict = {}

        with self.assertRaises(ValueError) as context:
            _verify_empty_cache_team(
                team=self.team,
                config=mock_config,
                cache_batch_data=cache_batch_data,
                expiry_status=None,
                cache_type="flags",
                result=result,
                team_ids_to_skip_fix=set(),
            )

        assert "empty_cache_value must be configured" in str(context.exception)
        assert str(self.team.id) in str(context.exception)

    def test_team_ids_to_skip_fix_skips_fix_for_empty_cache_team(self):
        """Test that team_ids_to_skip_fix can skip fixes in empty cache path."""
        mock_config = MagicMock()
        mock_config.empty_cache_value = {"flags": []}

        result = VerificationResult()
        # Cache miss - would normally trigger fix
        cache_batch_data: dict = {}
        # Team is in the skip set
        team_ids_to_skip_fix = {self.team.id}

        _verify_empty_cache_team(
            team=self.team,
            config=mock_config,
            cache_batch_data=cache_batch_data,
            expiry_status=None,
            cache_type="flags",
            result=result,
            team_ids_to_skip_fix=team_ids_to_skip_fix,
        )

        # Fix should be skipped
        assert result.total_fixed == 0
        assert result.skipped_for_grace_period == 1
        assert self.team.id in result.skipped_team_ids
        mock_config.hypercache.set_cache_value.assert_not_called()

    def test_empty_team_ids_to_skip_fix_does_not_skip_for_empty_cache_team(self):
        """Test that empty team_ids_to_skip_fix allows empty cache fixes to proceed."""
        mock_config = MagicMock()
        mock_config.empty_cache_value = {"flags": []}

        result = VerificationResult()
        # Cache miss - should trigger fix
        cache_batch_data: dict = {}
        # Empty skip set - should proceed with fix
        team_ids_to_skip_fix: set[int] = set()

        _verify_empty_cache_team(
            team=self.team,
            config=mock_config,
            cache_batch_data=cache_batch_data,
            expiry_status=None,
            cache_type="flags",
            result=result,
            team_ids_to_skip_fix=team_ids_to_skip_fix,
        )

        # Fix should proceed
        assert result.cache_miss_fixed == 1
        assert result.skipped_for_grace_period == 0


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyAndFixBatchOptimization(BaseTest):
    """Test _verify_and_fix_batch optimization path selection."""

    def test_teams_with_flags_use_full_verification_path(self):
        """Teams in team_ids_needing_full_verification should use full DB load."""
        mock_config = MagicMock()
        mock_config.empty_cache_value = {"flags": []}
        mock_config.hypercache.batch_load_fn.return_value = {self.team.id: {"flags": []}}
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.hypercache.get_cache_identifier.return_value = str(self.team.id)

        result = VerificationResult()
        verify_fn_calls = []

        def verify_fn(team, db_batch_data, cache_batch_data):
            verify_fn_calls.append(team.id)
            return {"status": "match", "issue": None}

        # Team with flags should be in the full check list
        team_ids_with_flags = {self.team.id}

        with patch(
            "posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={str(self.team.id): True}
        ):
            _verify_and_fix_batch(
                teams=[self.team],
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="flags",
                result=result,
                team_ids_needing_full_verification=team_ids_with_flags,
            )

        # Should have called batch_load_fn for teams with flags
        mock_config.hypercache.batch_load_fn.assert_called_once_with([self.team])
        # verify_fn should have been called (not _verify_empty_cache_team)
        assert len(verify_fn_calls) == 1
        assert verify_fn_calls[0] == self.team.id

    def test_teams_without_flags_use_empty_check_fast_path(self):
        """Teams NOT in team_ids_needing_full_verification should use fast-path."""
        mock_config = MagicMock()
        mock_config.empty_cache_value = {"flags": []}
        mock_config.hypercache.batch_load_fn = MagicMock(return_value={})
        mock_config.hypercache.batch_get_from_cache.return_value = {self.team.id: ({"flags": []}, "redis")}
        mock_config.hypercache.get_cache_identifier.return_value = str(self.team.id)

        result = VerificationResult()
        verify_fn_calls = []

        def verify_fn(team, db_batch_data, cache_batch_data):
            verify_fn_calls.append(team.id)
            return {"status": "match", "issue": None}

        # Team WITHOUT flags - empty optimization set means no teams have flags
        team_ids_with_flags: set[int] = set()

        with patch(
            "posthog.storage.hypercache_verifier.batch_check_expiry_tracking",
            return_value={str(self.team.id): True},
        ):
            _verify_and_fix_batch(
                teams=[self.team],
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="flags",
                result=result,
                team_ids_needing_full_verification=team_ids_with_flags,
            )

        # Should NOT have called batch_load_fn (no teams need full verification)
        mock_config.hypercache.batch_load_fn.assert_not_called()
        # verify_fn should NOT have been called (_verify_empty_cache_team was used instead)
        assert len(verify_fn_calls) == 0
        # But total should still count the team
        assert result.total == 1

    def test_optimization_fallback_when_function_fails(self):
        """When get_team_ids_needing_full_verification_fn fails, fall back to full verification."""
        mock_config = MagicMock()
        mock_config.get_team_ids_needing_full_verification_fn = MagicMock(
            side_effect=Exception("Database connection failed")
        )
        mock_config.hypercache.batch_load_fn = MagicMock(return_value={})
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.hypercache.get_cache_identifier.return_value = str(self.team.id)

        def verify_fn(team, db_batch_data, cache_batch_data):
            return {"status": "match", "issue": None}

        with patch(
            "posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={str(self.team.id): True}
        ):
            result = verify_and_fix_all_teams(
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                chunk_size=100,
            )

        # Should still complete successfully with full verification fallback
        assert result.total >= 1
        assert result.errors == 0
        # Should have used full verification path (batch_load_fn called)
        mock_config.hypercache.batch_load_fn.assert_called()
