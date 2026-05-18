from contextlib import contextmanager
from datetime import datetime

import pytest
from unittest.mock import MagicMock, call, patch

import dagster
from parameterized import parameterized

from posthog.dags.sessions import (
    BACKFILL_PROGRESS_TTL_SECONDS,
    MAX_UINT64,
    OOM_RETRY_SUB_CHUNKS,
    ExperimentalSessionsBackfillConfig,
    _do_experimental_backfill,
    _get_experimental_chunking,
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


ASSET_NAME = "experimental_sessions_v3_backfill"
PARTITION_KEY = "2025-06-15"


def _make_context(start: str = "2025-06-15", end: str = "2025-06-16") -> MagicMock:
    context = MagicMock()
    context.partition_time_window.start = datetime.strptime(start, "%Y-%m-%d")
    context.partition_time_window.end = datetime.strptime(end, "%Y-%m-%d")
    context.partition_key_range.start = start
    context.partition_key_range.end = end
    context.run_id = "test-run-id"
    context.asset_key.path = [ASSET_NAME]
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


class TestExperimentalBackfillResume:
    @parameterized.expand(
        [
            # (redis_get_return, force_fresh_restart, expected_call_count)
            ("saved_progress_chunk1", b"1", False, 2),
            ("no_saved_progress", None, False, 4),
            ("force_fresh_restart", b"1", True, 4),
            ("all_chunks_completed", b"3", False, 0),
        ]
    )
    def test_resume_call_count(self, _name, redis_val, force_fresh, expected_count):
        config = ExperimentalSessionsBackfillConfig(
            distinct_id_chunks=4, client_overrides={}, force_fresh_restart=force_fresh
        )
        context = _make_context()

        with _patch_experimental_backfill_deps(redis_get_return=redis_val) as (mock_sync_execute, _mock_redis):
            _do_experimental_backfill(
                sql_template=_sql_template_stub,
                timestamp_field="timestamp",
                context=context,
                config=config,
            )

        assert mock_sync_execute.call_count == expected_count

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

    def test_all_chunks_completed_clears_progress(self):
        config = ExperimentalSessionsBackfillConfig(distinct_id_chunks=4, client_overrides={})
        context = _make_context()
        key = _progress_key(ASSET_NAME, PARTITION_KEY)

        with _patch_experimental_backfill_deps(redis_get_return=b"3") as (_mock_sync_execute, mock_redis):
            _do_experimental_backfill(
                sql_template=_sql_template_stub,
                timestamp_field="timestamp",
                context=context,
                config=config,
            )

        mock_redis.delete.assert_called_once_with(key)

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


class TestTooManyPartsRetry:
    @staticmethod
    def _too_many_parts_error() -> Exception:
        return RuntimeError("Code: 252. DB::Exception: error code 252 TOO_MANY_PARTS: Too many parts")

    def test_retries_on_too_many_parts_then_succeeds(self):
        config = ExperimentalSessionsBackfillConfig(distinct_id_chunks=4, client_overrides={})
        context = _make_context()

        call_count = 0

        def fail_first_then_succeed(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise self._too_many_parts_error()

        with (
            _patch_experimental_backfill_deps() as (mock_sync_execute, _mock_redis),
            patch("posthog.dags.sessions.wait_for_parts_to_merge") as mock_wait,
        ):
            mock_sync_execute.side_effect = fail_first_then_succeed
            _do_experimental_backfill(
                sql_template=_sql_template_stub,
                timestamp_field="timestamp",
                context=context,
                config=config,
            )

        # 4 chunks, first one retried once = 5 executes total
        assert mock_sync_execute.call_count == 5
        # 4 preflight waits (one per chunk) + 1 retry wait = 5 waits
        assert mock_wait.call_count == 5

    def test_retry_budget_equals_num_chunks(self):
        num_chunks = 3
        config = ExperimentalSessionsBackfillConfig(distinct_id_chunks=num_chunks, client_overrides={})
        context = _make_context()

        with (
            _patch_experimental_backfill_deps() as (mock_sync_execute, _mock_redis),
            patch("posthog.dags.sessions.wait_for_parts_to_merge"),
        ):
            mock_sync_execute.side_effect = self._too_many_parts_error()
            with pytest.raises(dagster.Failure):
                _do_experimental_backfill(
                    sql_template=_sql_template_stub,
                    timestamp_field="timestamp",
                    context=context,
                    config=config,
                )

        # 1 initial + num_chunks retries, then the next retry exceeds the budget and re-raises
        assert mock_sync_execute.call_count == num_chunks + 1


class TestSubChunking:
    """Cover the OOM-retry sub-chunk where function returned by _get_experimental_chunking.

    Sub-chunks must partition by `cityHash64(distinct_id)` ranges so they line up with the
    events table primary index `(team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))`,
    and when the parent already chunks by `cityHash64(distinct_id)` ranges they must
    subdivide *that* range so each sub-chunk actually contains a fraction of the parent's data.
    """

    @pytest.mark.parametrize(
        "parent_i,all_have_upper_bound,all_have_lower_bound",
        [
            # First parent chunk: `< high`, so every sub-chunk has an upper bound but the very
            # first sub-chunk does not have a lower bound
            pytest.param(0, True, False, id="first_parent_chunk"),
            # Middle parent chunks: bounded on both sides, so every sub-chunk has both bounds
            pytest.param(1, True, True, id="middle_parent_chunk_1"),
            pytest.param(2, True, True, id="middle_parent_chunk_2"),
            # Last parent chunk: `>= low`, so every sub-chunk has a lower bound but the very
            # last sub-chunk does not have an upper bound
            pytest.param(3, False, True, id="last_parent_chunk"),
        ],
    )
    def test_distinct_id_sub_chunks_subdivide_parent_range(
        self, parent_i: int, all_have_upper_bound: bool, all_have_lower_bound: bool
    ):
        config = ExperimentalSessionsBackfillConfig(distinct_id_chunks=4, client_overrides={})
        num_chunks, _, _, sub_chunk_where_fn = _get_experimental_chunking(config)
        assert num_chunks == 4

        sub_filters = [sub_chunk_where_fn(parent_i, sub_i, 8) for sub_i in range(8)]

        # Every sub-chunk filters cityHash64(distinct_id) — primary-index aligned
        assert all("cityHash64(distinct_id)" in f for f in sub_filters)

        # Sub-chunks should be a strict subset of the parent's range — not span the whole uint64 space
        if all_have_upper_bound:
            assert all("<" in f for f in sub_filters)
        if all_have_lower_bound:
            assert all(">=" in f for f in sub_filters)

    def test_distinct_id_sub_chunks_cover_parent_range_without_gaps(self):
        config = ExperimentalSessionsBackfillConfig(distinct_id_chunks=4, client_overrides={})
        _num_chunks, _, _, sub_chunk_where_fn = _get_experimental_chunking(config)

        # Parent chunk 1 (middle) — bounded on both sides, easy to extract numbers
        sub_bounds = []
        for sub_i in range(8):
            f = sub_chunk_where_fn(1, sub_i, 8)
            # Filters look like "cityHash64(distinct_id) >= LOW AND cityHash64(distinct_id) < HIGH"
            parts = f.replace("cityHash64(distinct_id)", "").replace("AND", "").split()
            nums = [int(p) for p in parts if p.lstrip("-").isdigit()]
            sub_bounds.append(nums)

        # Each sub-chunk's high should equal the next sub-chunk's low — no gaps, no overlaps
        for i in range(len(sub_bounds) - 1):
            assert sub_bounds[i][1] == sub_bounds[i + 1][0], f"Gap between sub-chunk {i} and {i + 1}"

        # The first sub-chunk's low and the last sub-chunk's high should match the parent chunk's bounds
        parent_chunk_size = MAX_UINT64 // 4
        assert sub_bounds[0][0] == parent_chunk_size  # parent 1 starts at chunk_size
        assert sub_bounds[-1][1] == 2 * parent_chunk_size  # parent 1 ends at 2 * chunk_size

    @pytest.mark.parametrize("parent_i", [0, 1, 2])
    @pytest.mark.parametrize("sub_i", [0, 1, 2, 3])
    def test_team_id_sub_chunks_use_distinct_id_hash(self, parent_i: int, sub_i: int):
        # team_id parent uses modulo (not primary-index-aligned), but sub-chunks should still split by
        # cityHash64(distinct_id) ranges across the full uint64 space so the SELECT can skip granules.
        config = ExperimentalSessionsBackfillConfig(team_id_chunks=3, distinct_id_chunks=None, client_overrides={})
        num_chunks, _, _, sub_chunk_where_fn = _get_experimental_chunking(config)
        assert num_chunks == 3

        f = sub_chunk_where_fn(parent_i, sub_i, 4)
        assert f"team_id % {num_chunks} = {parent_i}" in f
        assert "cityHash64(distinct_id)" in f

    def test_no_chunk_sub_chunks_use_distinct_id_hash(self):
        # No parent chunking — sub-chunks should still split by cityHash64(distinct_id) ranges
        config = ExperimentalSessionsBackfillConfig(team_id_chunks=None, distinct_id_chunks=None, client_overrides={})
        num_chunks, _, _, sub_chunk_where_fn = _get_experimental_chunking(config)
        assert num_chunks == 1

        sub_filters = [sub_chunk_where_fn(0, sub_i, 4) for sub_i in range(4)]
        assert all("cityHash64(distinct_id)" in f for f in sub_filters)

    def test_oom_retry_executes_sub_chunks_within_parent_range(self):
        config = ExperimentalSessionsBackfillConfig(distinct_id_chunks=4, client_overrides={})
        context = _make_context()

        oom_error = RuntimeError("Code: 241. DB::Exception: error code 241 MEMORY_LIMIT_EXCEEDED: hit limit")
        call_count = 0

        def fail_first_chunk_then_succeed(sql, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            # Parent chunk 0 fails with OOM on first attempt → triggers sub-chunk retries
            if call_count == 1:
                raise oom_error

        with _patch_experimental_backfill_deps() as (mock_sync_execute, _mock_redis):
            mock_sync_execute.side_effect = fail_first_chunk_then_succeed
            _do_experimental_backfill(
                sql_template=_sql_template_stub,
                timestamp_field="timestamp",
                context=context,
                config=config,
            )

        executed = [c.args[0] for c in mock_sync_execute.call_args_list]
        # 1 failed parent + OOM_RETRY_SUB_CHUNKS sub-chunks for chunk 0 + 3 remaining parent chunks
        assert len(executed) == 1 + OOM_RETRY_SUB_CHUNKS + 3

        # Parent chunk 0 covers cityHash64(distinct_id) < MAX_UINT64/4 — every sub-chunk SQL
        # must stay within that range.
        parent_high = MAX_UINT64 // 4
        sub_chunk_sqls = executed[1 : 1 + OOM_RETRY_SUB_CHUNKS]
        for sql in sub_chunk_sqls:
            # Each sub-chunk must reference cityHash64(distinct_id) and not exceed the parent's high bound
            assert "cityHash64(distinct_id)" in sql
            # Pull out the largest integer literal in the sub-chunk filter — should be <= parent_high
            nums = [int(tok) for tok in sql.split() if tok.lstrip("-").isdigit()]
            big_nums = [n for n in nums if n > 1_000_000_000]  # filter out small numbers like dates
            assert max(big_nums) <= parent_high, (
                f"sub-chunk references hash {max(big_nums)} > parent_high {parent_high}: {sql}"
            )
