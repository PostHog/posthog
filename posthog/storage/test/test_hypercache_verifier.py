"""
Tests for HyperCache verification utilities.

Tests cover:
- VerificationResult tracking and formatting
- verify_and_fix_all_teams batch processing
- Auto-fix for cache issues (miss, mismatch, expiry_missing)
- Error handling and edge cases
"""

import time
from functools import partial

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, call, patch

from django.db import InterfaceError, OperationalError
from django.db.models import QuerySet
from django.test import SimpleTestCase, TestCase, override_settings

from celery.exceptions import SoftTimeLimitExceeded
from parameterized import parameterized

from posthog.models.team.team import Team
from posthog.storage.hypercache_manager import HyperCacheManagementConfig
from posthog.storage.hypercache_verifier import (
    MAX_FIXED_TEAM_IDS_TO_LOG,
    TEAM_BATCH_FETCH_MAX_ATTEMPTS,
    TeamBatchFetchError,
    VerificationResult,
    _fetch_team_batch,
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
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
        mock_config.update_fn.return_value = True

        result = VerificationResult()

        _fix_and_record(
            team=self.team,
            config=mock_config,
            issue_type=issue_type,
            cache_type="test_cache",
            result=result,
            verification={"status": issue_type},
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
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
        mock_config.update_fn.return_value = False

        result = VerificationResult()

        _fix_and_record(
            team=self.team,
            config=mock_config,
            issue_type="cache_miss",
            cache_type="test_cache",
            result=result,
            verification={"status": "miss"},
        )

        assert result.cache_miss_fixed == 0
        assert result.fix_failed == 1
        assert self.team.id not in result.fixed_team_ids

    @parameterized.expand(
        [
            ("under_cap", 0, True),
            ("at_cap", 1, False),
        ]
    )
    def test_fix_detail_info_log_respects_cap(self, _name, initial_logs_emitted, should_log):
        mock_config = MagicMock()
        mock_config.get_primary_writer_fn = None
        mock_config.update_fn.return_value = True

        result = VerificationResult(fix_detail_info_logs_emitted=initial_logs_emitted)

        with (
            patch("posthog.storage.hypercache_verifier.MAX_FIX_DETAIL_INFO_LOGS", 1),
            patch("posthog.storage.hypercache_verifier.logger.info") as mock_info,
        ):
            _fix_and_record(
                team=self.team,
                config=mock_config,
                issue_type="cache_mismatch",
                cache_type="test_cache",
                result=result,
                verification={"status": "mismatch", "diff_fields": ["payload"]},
            )

        fix_detail_call = call(
            "Fixing cache entry",
            team_id=self.team.id,
            issue_type="cache_mismatch",
            cache_type="test_cache",
            writer="python",
            diff_fields=["payload"],
        )
        if should_log:
            assert fix_detail_call in mock_info.call_args_list
        else:
            assert fix_detail_call not in mock_info.call_args_list
        assert result.fix_detail_info_logs_emitted == 1

    @parameterized.expand(
        [
            ("unattributed_defaults_to_python", None, "python"),
            ("attribution_fn_value_used", lambda team_id: "rust", "rust"),
            ("attribution_failure_is_unknown", MagicMock(side_effect=Exception("flag client down")), "unknown"),
        ]
    )
    def test_fix_metric_carries_primary_writer_label(self, _name, writer_fn, expected_writer):
        mock_config = MagicMock()
        mock_config.get_primary_writer_fn = writer_fn
        mock_config.should_skip_write = None
        mock_config.update_fn.return_value = True

        result = VerificationResult()

        with patch("posthog.storage.hypercache_verifier.HYPERCACHE_VERIFY_FIX_COUNTER") as mock_counter:
            _fix_and_record(
                team=self.team,
                config=mock_config,
                issue_type="cache_mismatch",
                cache_type="flags",
                result=result,
                verification={"status": "mismatch"},
            )

        mock_counter.labels.assert_called_once_with(
            cache_type="flags", issue_type="cache_mismatch", writer=expected_writer
        )
        # An attribution failure must not fail the repair itself.
        assert result.cache_mismatch_fixed == 1
        assert result.fix_failed == 0

    def test_exception_in_update_fn_increments_fix_failed(self):
        """Test that exception in update_fn increments fix_failed."""
        mock_config = MagicMock()
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
        mock_config.update_fn.side_effect = Exception("Update failed")

        result = VerificationResult()

        _fix_and_record(
            team=self.team,
            config=mock_config,
            issue_type="cache_miss",
            cache_type="test_cache",
            result=result,
            verification={"status": "miss"},
        )

        assert result.cache_miss_fixed == 0
        assert result.fix_failed == 1

    def test_uses_db_data_from_verification_directly(self):
        """Test that _fix_and_record uses verification['db_data'] to set cache directly, bypassing update_fn."""
        mock_config = MagicMock()
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
        db_data = {"flags": ["flag1", "flag2"]}

        result = VerificationResult()

        _fix_and_record(
            team=self.team,
            config=mock_config,
            issue_type="cache_miss",
            cache_type="test_cache",
            result=result,
            verification={"status": "miss", "db_data": db_data},
        )

        # Should call set_cache_value with db_data, NOT update_fn
        mock_config.hypercache.set_cache_value.assert_called_once_with(self.team, db_data)
        mock_config.update_fn.assert_not_called()
        assert result.cache_miss_fixed == 1
        assert self.team.id in result.fixed_team_ids

    def test_db_data_write_skipped_when_should_skip_write_vetoes(self):
        """A config write guard (e.g. group_type_mapping emptied) vetoes the direct
        db_data write, counting neither a fix nor a failure."""
        mock_config = MagicMock()
        mock_config.should_skip_write.return_value = True
        db_data: dict = {"flags": [], "group_type_mapping": {}}

        result = VerificationResult()

        _fix_and_record(
            team=self.team,
            config=mock_config,
            issue_type="cache_miss",
            cache_type="test_cache",
            result=result,
            verification={"status": "miss", "db_data": db_data},
        )

        mock_config.hypercache.set_cache_value.assert_not_called()
        assert result.cache_miss_fixed == 0
        assert result.fix_failed == 0

    @parameterized.expand(
        [
            ("empty_dict", {}),
            ("dict_without_db_data", {"status": "match", "issue": None}),
        ]
    )
    def test_falls_back_to_update_fn_when_no_db_data_in_verification(self, _name, verification):
        """Test that _fix_and_record falls back to update_fn when verification has no db_data."""
        mock_config = MagicMock()
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
        mock_config.update_fn.return_value = True

        result = VerificationResult()

        _fix_and_record(
            team=self.team,
            config=mock_config,
            issue_type="cache_miss",
            cache_type="test_cache",
            result=result,
            verification=verification,
        )

        # Should call update_fn, NOT set_cache_value
        mock_config.update_fn.assert_called_once_with(self.team)
        mock_config.hypercache.set_cache_value.assert_not_called()
        assert result.cache_miss_fixed == 1
        assert self.team.id in result.fixed_team_ids

    def test_db_data_set_cache_value_exception_increments_fix_failed(self):
        """Test that exceptions in set_cache_value (db_data path) increment fix_failed."""
        mock_config = MagicMock()
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
        mock_config.hypercache.set_cache_value.side_effect = Exception("Redis error")
        db_data = {"flags": ["flag1"]}

        result = VerificationResult()

        _fix_and_record(
            team=self.team,
            config=mock_config,
            issue_type="cache_miss",
            cache_type="test_cache",
            result=result,
            verification={"status": "miss", "db_data": db_data},
        )

        assert result.cache_miss_fixed == 0
        assert result.fix_failed == 1

    @parameterized.expand(
        [
            ("update_fn", False),
            ("set_cache_value", True),
        ]
    )
    def test_soft_time_limit_exceeded_propagates_instead_of_failing_fix(self, _name, use_db_data):
        """SoftTimeLimitExceeded must propagate so the task winds down cleanly,
        instead of being recorded as a fix failure like a real cache error (which
        previously happened because it subclasses Exception)."""
        mock_config = MagicMock()
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None

        verification: dict = {"status": "miss"}
        if use_db_data:
            verification["db_data"] = {"flags": ["flag1"]}
            mock_config.hypercache.set_cache_value.side_effect = SoftTimeLimitExceeded()
        else:
            mock_config.update_fn.side_effect = SoftTimeLimitExceeded()

        result = VerificationResult()

        with self.assertRaises(SoftTimeLimitExceeded):
            _fix_and_record(
                team=self.team,
                config=mock_config,
                issue_type="cache_miss",
                cache_type="test_cache",
                result=result,
                verification=verification,
            )

        assert result.fix_failed == 0
        assert result.cache_miss_fixed == 0


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyAndFixBatch(BaseTest):
    """Test _verify_and_fix_batch helper function."""

    def test_match_status_does_not_fix(self):
        """Test that cache match status doesn't trigger a fix."""
        mock_config = MagicMock()
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
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
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
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

    @parameterized.expand(
        [
            # A no-DB-fallback cache (repair_miss_during_grace_period=True) must repair a
            # miss even in the grace period, or the reader 503s until the next sweep. A
            # read-through cache (False) keeps the skip since it cold-loads on miss.
            (True, True),
            (False, False),
        ]
    )
    def test_grace_period_repair_miss_is_config_gated(self, repair_miss_during_grace_period, expect_fixed):
        mock_config = MagicMock()
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.update_fn.return_value = True
        mock_config.repair_miss_during_grace_period = repair_miss_during_grace_period
        # Team IS inside the grace period (recently updated), with a full miss.
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

        if expect_fixed:
            assert result.cache_miss_fixed == 1
            assert result.skipped_for_grace_period == 0
            mock_config.update_fn.assert_called_once_with(self.team)
        else:
            assert result.cache_miss_fixed == 0
            assert result.skipped_for_grace_period == 1
            mock_config.update_fn.assert_not_called()

    def test_expiry_missing_triggers_fix_for_match_status(self):
        """Test that missing expiry tracking triggers fix even when cache matches."""
        mock_config = MagicMock()
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
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
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
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

    def test_soft_time_limit_exceeded_propagates_and_stops_batch(self):
        """SoftTimeLimitExceeded from verify_team_fn must propagate so the run winds
        down, instead of being counted as a verification error and continuing on to
        the next team in the batch (which previously happened because it subclasses
        Exception)."""
        mock_config = MagicMock()
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}

        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        processed_team_ids: list[int] = []

        def verify_fn(team, db_batch_data, cache_batch_data):
            processed_team_ids.append(team.id)
            if team.id == self.team.id:
                raise SoftTimeLimitExceeded()
            return {"status": "match", "issue": None}

        result = VerificationResult()

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}):
            with self.assertRaises(SoftTimeLimitExceeded):
                _verify_and_fix_batch(
                    teams=[self.team, other_team],
                    config=mock_config,
                    verify_team_fn=verify_fn,
                    cache_type="test_cache",
                    result=result,
                )

        assert result.errors == 0
        assert processed_team_ids == [self.team.id]

    @parameterized.expand(
        [
            ("batch_get_from_cache",),
            ("get_team_ids_to_skip_fix_fn",),
            ("batch_load_fn",),
        ]
    )
    def test_soft_time_limit_exceeded_in_batch_setup_propagates(self, failing_attr):
        """A SoftTimeLimitExceeded from any of the batch-level setup calls (cache
        read, skip-fix check, DB load) must propagate, instead of being logged as a
        routine fallback warning and letting the batch continue toward the per-team
        loop."""
        mock_config = MagicMock()
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.hypercache.batch_load_fn.return_value = {}
        mock_config.get_team_ids_to_skip_fix_fn.return_value = set()
        if failing_attr == "get_team_ids_to_skip_fix_fn":
            mock_config.get_team_ids_to_skip_fix_fn.side_effect = SoftTimeLimitExceeded()
        else:
            getattr(mock_config.hypercache, failing_attr).side_effect = SoftTimeLimitExceeded()

        def verify_fn(team, db_batch_data, cache_batch_data):
            raise AssertionError("Should never reach per-team verification")

        result = VerificationResult()

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}):
            with self.assertRaises(SoftTimeLimitExceeded):
                _verify_and_fix_batch(
                    teams=[self.team],
                    config=mock_config,
                    verify_team_fn=verify_fn,
                    cache_type="test_cache",
                    result=result,
                )

        assert result.total == 0

    def test_batch_load_fn_called_when_available(self) -> None:
        mock_config = MagicMock()
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
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
    def test_fix_uses_db_data_from_verification(self, _name, base_verification_result, expiry_status, result_attr):
        """Test that fixes use db_data from verify_fn result to avoid redundant DB queries."""
        mock_config = MagicMock()
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
        mock_config.hypercache.batch_load_fn.return_value = {self.team.id: {"flags": ["flag1", "flag2"]}}
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.get_team_ids_to_skip_fix_fn = None

        result = VerificationResult()

        def verify_fn(team, db_batch_data, cache_batch_data):
            # Include db_data in verification result so _fix_and_record can use it directly
            return {**base_verification_result, "db_data": {"flags": ["flag1", "flag2"]}}

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value=expiry_status):
            _verify_and_fix_batch(
                teams=[self.team],
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                result=result,
            )

        # Should call set_cache_value with db_data from verification, NOT update_fn
        mock_config.hypercache.set_cache_value.assert_called_once_with(self.team, {"flags": ["flag1", "flag2"]})
        mock_config.update_fn.assert_not_called()
        assert getattr(result, result_attr) == 1

    def test_expiry_missing_fix_uses_batch_data_via_injection(self):
        """Test that expiry_missing fixes use batch-loaded db_data even when verify_fn omits it."""
        mock_config = MagicMock()
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
        mock_config.hypercache.batch_load_fn.return_value = {self.team.id: {"flags": ["flag1", "flag2"]}}
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        mock_config.hypercache.get_cache_identifier.return_value = str(self.team.id)
        mock_config.get_team_ids_to_skip_fix_fn = None

        result = VerificationResult()

        def verify_fn(team, db_batch_data, cache_batch_data):
            # Return match with no db_data - the batch infrastructure injects it
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

        # Batch infrastructure injects db_data, so set_cache_value is used (not update_fn)
        mock_config.hypercache.set_cache_value.assert_called_once_with(self.team, {"flags": ["flag1", "flag2"]})
        mock_config.update_fn.assert_not_called()
        assert result.expiry_missing_fixed == 1

    @parameterized.expand(
        [
            ("cache_miss", {"status": "miss", "issue": "CACHE_MISS"}, {}, "cache_miss_fixed"),
            ("cache_mismatch", {"status": "mismatch", "issue": "DATA_MISMATCH"}, {}, "cache_mismatch_fixed"),
        ]
    )
    def test_fix_uses_batch_data(self, _name, verification_result, expiry_status, result_attr):
        """Test that fixes use preloaded batch data via set_cache_value when available."""
        mock_config = MagicMock()
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
        db_data = {"flags": ["flag1", "flag2"]}
        mock_db_batch_data: dict = {self.team.id: db_data}
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

        # With batch data available, set_cache_value is used directly (avoiding redundant DB query)
        mock_config.hypercache.set_cache_value.assert_called_once_with(self.team, db_data)
        mock_config.update_fn.assert_not_called()
        assert getattr(result, result_attr) == 1

    def test_fix_falls_back_to_update_fn_without_batch_load(self):
        """Test that fixes fall back to update_fn when batch_load_fn is not available."""
        mock_config = MagicMock()
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
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
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
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

    def test_get_team_ids_to_skip_fix_fn_skips_mismatch_fix(self):
        """A mismatch on a skip-listed (recently updated) team is left for the in-flight
        async rebuild. (A miss is the exception — see test_grace_period_repair_miss_is_config_gated.)"""
        mock_config = MagicMock()
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
        mock_config.hypercache.batch_load_fn = None
        mock_config.hypercache.batch_get_from_cache.return_value = {}
        # Return team ID in the skip set
        mock_config.get_team_ids_to_skip_fix_fn.return_value = {self.team.id}

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
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
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
        mock_config.should_skip_write = None  # default: no write guard
        mock_config.get_primary_writer_fn = None
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


def _make_verifier_config(teams_queryset: QuerySet[Team], refresh_only_fields: list[str] | None = None) -> MagicMock:
    """Mock config with real-config defaults: bare MagicMock attributes are truthy where
    HyperCacheManagementConfig defaults to None, and narrow_team_queryset must run for
    real so the verifier gets an actual queryset back."""
    config = MagicMock()
    config.refresh_only_fields = refresh_only_fields
    config.should_skip_write = None
    config.get_team_ids_to_skip_fix_fn = None
    config.get_primary_writer_fn = None
    config.get_teams_queryset.return_value = teams_queryset
    config.narrow_team_queryset.side_effect = partial(HyperCacheManagementConfig.narrow_team_queryset, config)
    config.hypercache.batch_load_fn = None
    config.hypercache.batch_get_from_cache.return_value = {}
    config.hypercache.get_cache_identifier.side_effect = lambda t: str(t.id)
    return config


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyAndFixAllTeams(BaseTest):
    """Test verify_and_fix_all_teams function."""

    def test_processes_all_teams_in_chunks(self):
        """Test that all teams are processed in chunks."""
        mock_config = _make_verifier_config(Team.objects.all())

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

    def test_narrows_selected_columns_to_refresh_fields(self):
        """refresh_only_fields narrows the batch SELECT so a replica-lag UndefinedColumn can't abort a sweep."""
        mock_config = _make_verifier_config(
            Team.objects.all(), refresh_only_fields=["id", "project_id", "organization_id"]
        )

        seen_teams: list[Team] = []

        def verify_fn(team, db_batch_data, cache_batch_data):
            seen_teams.append(team)
            return {"status": "match", "issue": None}

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}):
            verify_and_fix_all_teams(
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                chunk_size=100,
            )

        assert seen_teams
        deferred = seen_teams[0].get_deferred_fields()
        # Columns outside the refresh set are deferred — a SELECT * regression leaves this empty.
        assert deferred
        # None of the refresh fields are deferred, so verification never triggers a per-field lazy load.
        assert deferred & set(mock_config.refresh_only_fields) == set()

    def test_returns_aggregated_results(self):
        """Test that results are aggregated across all chunks."""
        mock_config = _make_verifier_config(Team.objects.all())
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

    def test_fixed_batches_under_progress_interval_emit_batch_fix_logs(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")

        mock_config = _make_verifier_config(Team.objects.filter(id__in=[self.team.id, team2.id]))
        mock_config.update_fn.return_value = True

        def verify_fn(team, db_batch_data, cache_batch_data):
            return {"status": "miss", "issue": "CACHE_MISS"}

        with (
            patch("posthog.storage.hypercache_verifier.MAX_FIX_DETAIL_INFO_LOGS", 0),
            patch("posthog.storage.hypercache_verifier.PROGRESS_LOG_BATCH_INTERVAL", 999),
            patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}),
            patch("posthog.storage.hypercache_verifier.logger.info") as mock_info,
        ):
            result = verify_and_fix_all_teams(
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                chunk_size=1,
            )

        assert result.total == 2
        assert result.total_fixed == 2
        assert [mock_call.args for mock_call in mock_info.call_args_list] == [
            ("Batch completed with fixes",),
            ("Batch completed with fixes",),
        ]
        assert [mock_call.kwargs["batch_number"] for mock_call in mock_info.call_args_list] == [1, 2]
        assert [mock_call.kwargs["batch_verified"] for mock_call in mock_info.call_args_list] == [1, 1]
        assert [mock_call.kwargs["batch_fixed"] for mock_call in mock_info.call_args_list] == [1, 1]
        assert [mock_call.kwargs["teams_verified_total"] for mock_call in mock_info.call_args_list] == [1, 2]
        assert [mock_call.kwargs["teams_fixed_total"] for mock_call in mock_info.call_args_list] == [1, 2]

    def test_fix_detail_info_logs_are_capped_during_verification_run(self):
        teams = [
            self.team,
            Team.objects.create(organization=self.organization, name="Team 2"),
            Team.objects.create(organization=self.organization, name="Team 3"),
        ]

        mock_config = _make_verifier_config(Team.objects.filter(id__in=[team.id for team in teams]))
        mock_config.update_fn.return_value = True

        def verify_fn(team, db_batch_data, cache_batch_data):
            return {"status": "miss", "issue": "CACHE_MISS"}

        with (
            patch("posthog.storage.hypercache_verifier.MAX_FIX_DETAIL_INFO_LOGS", 2),
            patch("posthog.storage.hypercache_verifier.PROGRESS_LOG_BATCH_INTERVAL", 999),
            patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}),
            patch("posthog.storage.hypercache_verifier.logger.info") as mock_info,
        ):
            result = verify_and_fix_all_teams(
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                chunk_size=1,
            )

        fix_detail_calls = [
            mock_call for mock_call in mock_info.call_args_list if mock_call.args == ("Fixing cache entry",)
        ]
        assert len(fix_detail_calls) == 2
        assert result.fix_detail_info_logs_emitted == 2
        assert result.total == 3
        assert result.total_fixed == 3

    def test_periodic_progress_log_reports_aggregate_fix_and_failure_counts(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")

        mock_config = _make_verifier_config(Team.objects.filter(id__in=[self.team.id, team2.id]))
        mock_config.update_fn.side_effect = [True, False]

        def verify_fn(team, db_batch_data, cache_batch_data):
            return {"status": "miss", "issue": "CACHE_MISS"}

        with (
            patch("posthog.storage.hypercache_verifier.MAX_FIX_DETAIL_INFO_LOGS", 0),
            patch("posthog.storage.hypercache_verifier.PROGRESS_LOG_BATCH_INTERVAL", 1),
            patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}),
            patch("posthog.storage.hypercache_verifier.logger.info") as mock_info,
        ):
            result = verify_and_fix_all_teams(
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                chunk_size=2,
            )

        assert result.total == 2
        assert result.total_fixed == 1
        assert result.fix_failed == 1
        mock_info.assert_called_once()

        call_args = mock_info.call_args
        assert call_args.args == ("Verification progress",)
        assert call_args.kwargs["batch_fixed"] == 1
        assert call_args.kwargs["batch_fix_failures"] == 1
        assert call_args.kwargs["teams_verified_total"] == 2
        assert call_args.kwargs["teams_fixed_total"] == 1
        assert call_args.kwargs["cache_miss_fixed_total"] == 1
        assert call_args.kwargs["cache_mismatch_fixed_total"] == 0
        assert call_args.kwargs["expiry_missing_fixed_total"] == 0
        assert call_args.kwargs["fix_failures_total"] == 1


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyAndFixAllTeamsQuerysetScoping(BaseTest):
    """Test that verify_and_fix_all_teams uses get_teams_queryset() for team scoping."""

    def test_scopes_to_queryset_when_configured(self):
        """Only teams returned by get_teams_queryset() are verified."""
        team2 = Team.objects.create(organization=self.organization, name="Team 2")

        mock_config = _make_verifier_config(Team.objects.filter(id=team2.id))

        verified_team_ids: list[int] = []

        def verify_fn(team, db_batch_data, cache_batch_data):
            verified_team_ids.append(team.id)
            return {"status": "match", "issue": None}

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}):
            result = verify_and_fix_all_teams(
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                chunk_size=100,
            )

        assert result.total == 1
        assert team2.id in verified_team_ids
        assert self.team.id not in verified_team_ids

    def test_empty_queryset_processes_zero_teams(self):
        """When get_teams_queryset() returns empty queryset, no teams are verified."""
        mock_config = _make_verifier_config(Team.objects.none())

        def verify_fn(team, db_batch_data, cache_batch_data):
            raise AssertionError("Should never be called")

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}):
            result = verify_and_fix_all_teams(
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                chunk_size=100,
            )

        assert result.total == 0

    def test_iterates_all_teams_when_queryset_fn_is_none(self):
        """When get_teams_queryset() has no scoping function, all teams are verified."""
        mock_config = _make_verifier_config(Team.objects.all())

        def verify_fn(team, db_batch_data, cache_batch_data):
            return {"status": "match", "issue": None}

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}):
            result = verify_and_fix_all_teams(
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                chunk_size=100,
            )

        # Should have verified at least self.team
        assert result.total >= 1


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyAndFixAllTeamsDeadline(BaseTest):
    @parameterized.expand(
        [
            # A passed deadline breaks after the first (chunk_size=1) batch, leaving the
            # second team for the next cycle; headroom processes both teams.
            ("deadline_passed", 1, -1.0, True, 1),
            ("headroom", 1, 3600.0, False, 2),
            # Both teams fit in one batch, so nothing remains when the deadline trips on it:
            # the sweep completed and must not record a false early wind-down.
            ("deadline_passed_final_batch", 2, -1.0, False, 2),
        ]
    )
    def test_winds_down_at_batch_boundary_once_deadline_passes(
        self, _name: str, chunk_size: int, stop_time_offset: float, expected_wound_down: bool, expected_total: int
    ) -> None:
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        mock_config = _make_verifier_config(Team.objects.filter(id__in=[self.team.id, team2.id]))

        def verify_fn(team, db_batch_data, cache_batch_data):
            return {"status": "match", "issue": None}

        with patch("posthog.storage.hypercache_verifier.batch_check_expiry_tracking", return_value={}):
            result = verify_and_fix_all_teams(
                config=mock_config,
                verify_team_fn=verify_fn,
                cache_type="test_cache",
                chunk_size=chunk_size,
                stop_time=time.monotonic() + stop_time_offset,
            )

        assert result.wound_down_early is expected_wound_down
        assert result.total == expected_total


class _FlakyTeamQuerySet:
    """Fake queryset that raises the given errors before yielding teams, mimicking a
    connection dropped by the pooler mid-sweep."""

    def __init__(self, errors: list[Exception], teams: list[Team]) -> None:
        self.errors = errors
        self.teams = teams
        self.requested_after_ids: list[int] = []

    def filter(self, *, id__gt: int) -> "_FlakyTeamQuerySet":
        self.requested_after_ids.append(id__gt)
        return self

    def order_by(self, *_fields: str) -> "_FlakyTeamQuerySet":
        return self

    def __getitem__(self, _key) -> list[Team]:
        if self.errors:
            raise self.errors.pop(0)
        return self.teams


class TestFetchTeamBatch(SimpleTestCase):
    @parameterized.expand(
        [
            ("connection_timeout", OperationalError("connection timeout expired")),
            ("connection_closed", InterfaceError("the connection is closed")),
        ]
    )
    def test_reconnects_and_resumes_from_last_id(self, _name, error):
        team = Team(id=7)
        base_qs = _FlakyTeamQuerySet([error], [team])

        with (
            patch("posthog.storage.hypercache_verifier.close_old_connections") as mock_close,
            patch("posthog.storage.hypercache_verifier.time.sleep"),
        ):
            teams = _fetch_team_batch(base_qs, last_id=3, chunk_size=10)  # type: ignore[arg-type]

        assert teams == [team]
        mock_close.assert_called_once()
        # The retry resumes from the same cursor, so no team is skipped.
        assert base_qs.requested_after_ids == [3, 3]

    def test_raises_team_batch_fetch_error_once_retries_are_exhausted(self):
        errors: list[Exception] = [
            OperationalError("too many clients already") for _ in range(TEAM_BATCH_FETCH_MAX_ATTEMPTS)
        ]
        base_qs = _FlakyTeamQuerySet(errors, [])

        with (
            patch("posthog.storage.hypercache_verifier.close_old_connections"),
            patch("posthog.storage.hypercache_verifier.time.sleep"),
            self.assertRaises(TeamBatchFetchError),
        ):
            _fetch_team_batch(base_qs, last_id=0, chunk_size=10)  # type: ignore[arg-type]

        assert len(base_qs.requested_after_ids) == TEAM_BATCH_FETCH_MAX_ATTEMPTS

    @parameterized.expand(
        [
            ("soft_time_limit", SoftTimeLimitExceeded()),
            ("unexpected_error", ValueError("bad verify data")),
        ]
    )
    def test_non_connection_error_propagates_without_retry_or_wrapping(self, _name, error):
        base_qs = _FlakyTeamQuerySet([error], [Team(id=7)])

        with (
            patch("posthog.storage.hypercache_verifier.close_old_connections") as mock_close,
            patch("posthog.storage.hypercache_verifier.time.sleep"),
            self.assertRaises(type(error)),
        ):
            _fetch_team_batch(base_qs, last_id=0, chunk_size=10)  # type: ignore[arg-type]

        assert base_qs.requested_after_ids == [0]
        mock_close.assert_not_called()

    def test_sweep_aborts_when_batch_fetch_retries_are_exhausted(self):
        errors: list[Exception] = [OperationalError("connection dropped") for _ in range(TEAM_BATCH_FETCH_MAX_ATTEMPTS)]
        flaky_qs = _FlakyTeamQuerySet(errors, [])
        config = MagicMock()
        config.narrow_team_queryset.return_value = flaky_qs

        with (
            patch("posthog.storage.hypercache_verifier.close_old_connections"),
            patch("posthog.storage.hypercache_verifier.time.sleep"),
            self.assertRaises(TeamBatchFetchError),
        ):
            verify_and_fix_all_teams(
                config=config,
                verify_team_fn=lambda team, db, cached: {"status": "match", "issue": None},
                cache_type="test_cache",
                chunk_size=10,
            )
