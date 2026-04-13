from contextlib import contextmanager
from datetime import datetime

import pytest
from unittest.mock import MagicMock, call, patch

import dagster
from parameterized import parameterized

from posthog.dags.sessions import (
    BACKFILL_PROGRESS_TTL_SECONDS,
    ExperimentalSessionsBackfillConfig,
    _do_experimental_backfill,
    _progress_key,
    tags_for_sessions_partition,
)


class TestTagsForSessionsPartition:
    @parameterized.expand(
        [
            # (partition_key, expected_partition_0, expected_partition_1)
            # Mid-month: both tags have same value
            ("2025-10-15", "s0_202510", "s1_202510"),
            # End of month: both tags have same value
            ("2025-10-31", "s0_202510", "s1_202510"),
            # First of month: tags differ (current month and previous month)
            ("2025-11-01", "s0_202511", "s1_202510"),
            # Day after first: both tags have same value again
            ("2025-11-02", "s0_202511", "s1_202511"),
            # January 1st: crosses year boundary
            ("2025-01-01", "s0_202501", "s1_202412"),
            # Another first of month
            ("2025-12-01", "s0_202512", "s1_202511"),
        ]
    )
    def test_tags_for_sessions_partition(self, partition_key, expected_partition_0, expected_partition_1):
        result = tags_for_sessions_partition(partition_key)

        assert result == {
            "sessions_db_partition_0": expected_partition_0,
            "sessions_db_partition_1": expected_partition_1,
        }


def _make_context(start: str = "2025-06-15", end: str = "2025-06-16") -> MagicMock:
    context = MagicMock()
    context.partition_time_window.start = datetime.strptime(start, "%Y-%m-%d")
    context.partition_time_window.end = datetime.strptime(end, "%Y-%m-%d")
    context.partition_key_range.start = start
    context.partition_key_range.end = end
    context.run_id = "test-run-id"
    return context


@contextmanager
def _patch_experimental_backfill_deps(redis_get_return=None):
    """Patch external dependencies so _do_experimental_backfill can run without ClickHouse."""
    mock_client = MagicMock()
    mock_redis = MagicMock()
    mock_redis.get.return_value = redis_get_return

    with (
        patch("posthog.dags.sessions.get_kwargs_for_client", return_value={}),
        patch("posthog.dags.sessions.get_http_client") as mock_get_http_client,
        patch("posthog.dags.sessions.sync_execute") as mock_sync_execute,
        patch("posthog.dags.sessions.wait_for_parts_to_merge"),
        patch("posthog.dags.sessions.get_git_commit_short", return_value="abc123"),
        patch("posthog.dags.sessions.metabase_debug_query_url", return_value=None),
        patch("posthog.dags.sessions.get_redis_client", return_value=mock_redis),
    ):
        mock_get_http_client.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_get_http_client.return_value.__exit__ = MagicMock(return_value=False)
        yield mock_sync_execute, mock_redis


def _sql_template_stub(where: str, target_table: str, include_session_timestamp: bool) -> str:
    return f"INSERT INTO {target_table} SELECT ... WHERE {where}"


class TestExperimentalBackfillChunking:
    @pytest.mark.parametrize(
        "config_kwargs",
        [
            pytest.param({"distinct_id_chunks": 4}, id="distinct_id_chunks"),
            pytest.param({"team_id_chunks": 3, "distinct_id_chunks": None}, id="team_id_chunks"),
            pytest.param({"team_id_chunks": None, "distinct_id_chunks": None}, id="no_chunks"),
        ],
    )
    def test_chunking_sql(self, config_kwargs, snapshot):
        config = ExperimentalSessionsBackfillConfig(**config_kwargs, client_overrides={})
        context = _make_context()

        with _patch_experimental_backfill_deps() as (mock_sync_execute, _mock_redis):
            _do_experimental_backfill(
                sql_template=_sql_template_stub,
                timestamp_field="timestamp",
                context=context,
                config=config,
            )

        executed_sqls = [c.args[0] for c in mock_sync_execute.call_args_list]
        assert executed_sqls == snapshot

    def test_both_chunking_strategies_raises(self):
        config = ExperimentalSessionsBackfillConfig(team_id_chunks=32, distinct_id_chunks=64, client_overrides={})
        context = _make_context()

        with _patch_experimental_backfill_deps():
            with pytest.raises(ValueError, match="Cannot specify both"):
                _do_experimental_backfill(
                    sql_template=_sql_template_stub,
                    timestamp_field="timestamp",
                    context=context,
                    config=config,
                )


ASSET_NAME = "experimental_sessions_v3_backfill"
PARTITION_KEY = "2025-06-15"


class TestExperimentalBackfillResume:
    def test_resume_from_saved_progress(self):
        config = ExperimentalSessionsBackfillConfig(distinct_id_chunks=4, client_overrides={})
        context = _make_context()

        with _patch_experimental_backfill_deps(redis_get_return=b"1") as (mock_sync_execute, mock_redis):
            _do_experimental_backfill(
                sql_template=_sql_template_stub,
                timestamp_field="timestamp",
                context=context,
                config=config,
            )

        # Chunks 0 and 1 skipped, only 2 and 3 executed
        assert mock_sync_execute.call_count == 2

    def test_no_saved_progress_starts_from_zero(self):
        config = ExperimentalSessionsBackfillConfig(distinct_id_chunks=4, client_overrides={})
        context = _make_context()

        with _patch_experimental_backfill_deps(redis_get_return=None) as (mock_sync_execute, _mock_redis):
            _do_experimental_backfill(
                sql_template=_sql_template_stub,
                timestamp_field="timestamp",
                context=context,
                config=config,
            )

        assert mock_sync_execute.call_count == 4

    def test_force_fresh_restart_ignores_saved_progress(self):
        config = ExperimentalSessionsBackfillConfig(distinct_id_chunks=4, client_overrides={}, force_fresh_restart=True)
        context = _make_context()

        with _patch_experimental_backfill_deps(redis_get_return=b"1") as (mock_sync_execute, _mock_redis):
            _do_experimental_backfill(
                sql_template=_sql_template_stub,
                timestamp_field="timestamp",
                context=context,
                config=config,
            )

        assert mock_sync_execute.call_count == 4

    def test_progress_saved_after_each_chunk(self):
        config = ExperimentalSessionsBackfillConfig(distinct_id_chunks=3, client_overrides={})
        context = _make_context()
        key = _progress_key(ASSET_NAME, PARTITION_KEY)

        with _patch_experimental_backfill_deps() as (_mock_sync_execute, mock_redis):
            _do_experimental_backfill(
                sql_template=_sql_template_stub,
                timestamp_field="timestamp",
                context=context,
                config=config,
            )

        set_calls = [c for c in mock_redis.set.call_args_list if c.args[0] == key]
        assert len(set_calls) == 3
        assert set_calls[0] == call(key, "0", ex=BACKFILL_PROGRESS_TTL_SECONDS)
        assert set_calls[1] == call(key, "1", ex=BACKFILL_PROGRESS_TTL_SECONDS)
        assert set_calls[2] == call(key, "2", ex=BACKFILL_PROGRESS_TTL_SECONDS)

    def test_progress_cleared_on_completion(self):
        config = ExperimentalSessionsBackfillConfig(distinct_id_chunks=2, client_overrides={})
        context = _make_context()
        key = _progress_key(ASSET_NAME, PARTITION_KEY)

        with _patch_experimental_backfill_deps() as (_mock_sync_execute, mock_redis):
            _do_experimental_backfill(
                sql_template=_sql_template_stub,
                timestamp_field="timestamp",
                context=context,
                config=config,
            )

        mock_redis.delete.assert_called_once_with(key)

    def test_all_chunks_completed_is_noop(self):
        config = ExperimentalSessionsBackfillConfig(distinct_id_chunks=4, client_overrides={})
        context = _make_context()

        # last_completed=3 means all 4 chunks (0-3) are done
        with _patch_experimental_backfill_deps(redis_get_return=b"3") as (mock_sync_execute, _mock_redis):
            _do_experimental_backfill(
                sql_template=_sql_template_stub,
                timestamp_field="timestamp",
                context=context,
                config=config,
            )

        assert mock_sync_execute.call_count == 0

    def test_non_oom_error_raises_dagster_failure_with_metadata(self):
        config = ExperimentalSessionsBackfillConfig(distinct_id_chunks=4, client_overrides={})
        context = _make_context()

        call_count = 0

        def fail_on_third_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise RuntimeError("Connection lost")

        with _patch_experimental_backfill_deps() as (mock_sync_execute, _mock_redis):
            mock_sync_execute.side_effect = fail_on_third_call
            with pytest.raises(dagster.Failure) as exc_info:
                _do_experimental_backfill(
                    sql_template=_sql_template_stub,
                    timestamp_field="timestamp",
                    context=context,
                    config=config,
                )

        failure = exc_info.value
        assert failure.metadata["failed_chunk_index"].value == 2
        assert failure.metadata["resume_from_chunk"].value == 2
        assert failure.metadata["total_chunks"].value == 4
