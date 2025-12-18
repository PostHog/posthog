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
    _verify_and_fix_batch,
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
        assert result.fixed_team_ids == []

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


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestFixAndRecord(BaseTest):
    """Test _fix_and_record helper function."""

    def test_successful_fix_increments_cache_miss_fixed(self):
        """Test that successful fix for cache_miss increments the right counter."""
        mock_config = MagicMock()
        mock_config.update_fn.return_value = True

        result = VerificationResult()

        _fix_and_record(
            team=self.team,
            config=mock_config,
            issue_type="cache_miss",
            cache_type="test_cache",
            result=result,
        )

        assert result.cache_miss_fixed == 1
        assert result.cache_mismatch_fixed == 0
        assert result.expiry_missing_fixed == 0
        assert result.fix_failed == 0
        assert self.team.id in result.fixed_team_ids

    def test_successful_fix_increments_cache_mismatch_fixed(self):
        """Test that successful fix for cache_mismatch increments the right counter."""
        mock_config = MagicMock()
        mock_config.update_fn.return_value = True

        result = VerificationResult()

        _fix_and_record(
            team=self.team,
            config=mock_config,
            issue_type="cache_mismatch",
            cache_type="test_cache",
            result=result,
        )

        assert result.cache_miss_fixed == 0
        assert result.cache_mismatch_fixed == 1
        assert result.expiry_missing_fixed == 0
        assert result.fix_failed == 0

    def test_successful_fix_increments_expiry_missing_fixed(self):
        """Test that successful fix for expiry_missing increments the right counter."""
        mock_config = MagicMock()
        mock_config.update_fn.return_value = True

        result = VerificationResult()

        _fix_and_record(
            team=self.team,
            config=mock_config,
            issue_type="expiry_missing",
            cache_type="test_cache",
            result=result,
        )

        assert result.cache_miss_fixed == 0
        assert result.cache_mismatch_fixed == 0
        assert result.expiry_missing_fixed == 1
        assert result.fix_failed == 0

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

    def test_uses_db_data_directly_when_provided(self):
        """Test that _fix_and_record uses db_data to set cache directly, bypassing update_fn."""
        mock_config = MagicMock()
        db_data = {"flags": ["flag1", "flag2"]}

        result = VerificationResult()

        _fix_and_record(
            team=self.team,
            config=mock_config,
            issue_type="cache_miss",
            cache_type="test_cache",
            result=result,
            db_data=db_data,
        )

        # Should call set_cache_value with db_data, NOT update_fn
        mock_config.hypercache.set_cache_value.assert_called_once_with(self.team, db_data)
        mock_config.update_fn.assert_not_called()
        assert result.cache_miss_fixed == 1

    def test_falls_back_to_update_fn_when_db_data_is_none(self):
        """Test that _fix_and_record falls back to update_fn when db_data is None."""
        mock_config = MagicMock()
        mock_config.update_fn.return_value = True

        result = VerificationResult()

        _fix_and_record(
            team=self.team,
            config=mock_config,
            issue_type="cache_miss",
            cache_type="test_cache",
            result=result,
            db_data=None,
        )

        # Should call update_fn, NOT set_cache_value
        mock_config.update_fn.assert_called_once_with(self.team)
        mock_config.hypercache.set_cache_value.assert_not_called()
        assert result.cache_miss_fixed == 1

    def test_db_data_set_cache_value_exception_increments_fix_failed(self):
        """Test that exceptions in set_cache_value (db_data path) increment fix_failed."""
        mock_config = MagicMock()
        mock_config.hypercache.set_cache_value.side_effect = Exception("Redis error")
        db_data = {"flags": ["flag1"]}

        result = VerificationResult()

        _fix_and_record(
            team=self.team,
            config=mock_config,
            issue_type="cache_miss",
            cache_type="test_cache",
            result=result,
            db_data=db_data,
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

    def test_miss_status_triggers_fix(self):
        """Test that cache miss status triggers a fix."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}
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

        assert result.total == 1
        assert result.cache_miss_fixed == 1
        # When db_batch_data is None (no batch_load_fn), it falls back to update_fn
        mock_config.update_fn.assert_called_once_with(self.team)

    def test_mismatch_status_triggers_fix(self):
        """Test that cache mismatch status triggers a fix."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.update_fn.return_value = True

        result = VerificationResult()

        def verify_fn(team, db_batch_data, cache_batch_data):
            return {"status": "mismatch", "issue": "DATA_MISMATCH"}

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}):
            _verify_and_fix_batch(
                teams=[self.team],
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                result=result,
            )

        assert result.total == 1
        assert result.cache_mismatch_fixed == 1

    def test_expiry_missing_triggers_fix_for_match_status(self):
        """Test that missing expiry tracking triggers fix even when cache matches."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.hypercache.get_cache_identifier.return_value = str(self.team.id)
        mock_config.update_fn.return_value = True

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

    def test_fix_uses_db_batch_data_directly(self):
        """Test that fixes use pre-loaded db_batch_data to avoid redundant DB queries."""
        mock_config = MagicMock()
        mock_db_batch_data: dict = {self.team.id: {"flags": ["flag1", "flag2"]}}
        mock_config.hypercache.batch_load_fn.return_value = mock_db_batch_data
        mock_config.hypercache.batch_get_from_cache.return_value = {}

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

        # Should call set_cache_value with db_batch_data, NOT update_fn
        mock_config.hypercache.set_cache_value.assert_called_once_with(self.team, {"flags": ["flag1", "flag2"]})
        mock_config.update_fn.assert_not_called()
        assert result.cache_miss_fixed == 1

    def test_fix_falls_back_to_update_fn_without_batch_load(self):
        """Test that fixes fall back to update_fn when batch_load_fn is not available."""
        mock_config = MagicMock()
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}
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

        # Should call update_fn, NOT set_cache_value
        mock_config.update_fn.assert_called_once_with(self.team)
        mock_config.hypercache.set_cache_value.assert_not_called()
        assert result.cache_miss_fixed == 1


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
