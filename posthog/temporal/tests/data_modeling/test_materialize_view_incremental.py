"""Incremental materialization, exercised against real deltalite and real Delta tables.

Mocked out here: only ``hogql_table`` (so a test controls exactly which rows a "run" returns) and
the feature flags. The write path itself is real, because every load-bearing unknown lives in the
Rust crate — key matching, duplicate rejection, schema handling, column-name case — and a mock
would assert our idea of deltalite rather than deltalite.
"""

import asyncio
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
import unittest.mock

from django.conf import settings
from django.test import override_settings

import pyarrow as pa
import deltalake

from posthog.sync import database_sync_to_async
from posthog.temporal.data_modeling.activities import MaterializeViewInputs, materialize_view_activity
from posthog.temporal.data_modeling.activities.incremental_write import IncrementalWriteError
from posthog.temporal.data_modeling.activities.materialize_view import get_aws_storage_options

from products.data_modeling.backend.facade.api import get_incremental_state

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

CONFIG = {"enabled": True, "incremental_key": "day", "unique_key": ["day"]}

DAY1 = datetime(2026, 8, 1, tzinfo=UTC)
DAY2 = datetime(2026, 8, 2, tzinfo=UTC)
DAY3 = datetime(2026, 8, 3, tzinfo=UTC)


def _batch(days: list[datetime | None], counts: list[int], *, value_column: str = "c") -> pa.RecordBatch:
    arrays = cast(
        Collection[pa.Array],
        [pa.array(days, type=pa.timestamp("us", tz="UTC")), pa.array(counts, type=pa.int64())],
    )
    return pa.RecordBatch.from_arrays(arrays, names=["day", value_column])


def _rows(table_uri: str) -> list[tuple[Any, Any]]:
    """Stored rows as (day, value), sorted, so tests assert content rather than counts."""
    table = deltalake.DeltaTable(table_uri, storage_options=get_aws_storage_options()).to_pyarrow_table()
    value_column = next(name for name in table.column_names if name != "day")
    pairs = list(zip(table.column("day").to_pylist(), table.column(value_column).to_pylist()))
    return sorted(pairs, key=lambda pair: (pair[0] is None, pair[0]))


def _mock_hogql_table(*batches: pa.RecordBatch, value_column: str = "c", windows: list[Any] | None = None):
    """Stand in for one run: yields the given batches, ignoring the window.

    The window's effect on the generated SQL is covered by the filter-injection tests; what matters
    here is what the write path does with the rows that come back. ``windows`` collects the window
    each run was given, for tests that assert on the computed lower bound.
    """

    def factory(*args, **kwargs):
        if windows is not None:
            windows.append(kwargs.get("window"))
        del args, kwargs

        async def generator():
            for batch in batches:
                # DateTime64 so the activity's arrow transform passes an already-typed timestamp
                # through, the way it does for a real ClickHouse DateTime64 column.
                yield batch, [("day", "DateTime64(6, 'UTC')"), (value_column, "Int64")]

        return generator()

    return factory


def _settings(bucket_name: str):
    return override_settings(
        BUCKET_URL=f"s3://{bucket_name}",
        DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
    )


async def _run(
    activity_environment,
    ateam,
    anode,
    ajob,
    adag,
    *batches: pa.RecordBatch,
    enabled: bool = True,
    value_column: str = "c",
    windows: list[Any] | None = None,
):
    with (
        unittest.mock.patch(
            "posthog.temporal.data_modeling.activities.materialize_view.hogql_table",
            _mock_hogql_table(*batches, value_column=value_column, windows=windows),
        ),
        unittest.mock.patch(
            "posthog.temporal.data_modeling.activities.materialize_view._incremental_enabled",
            return_value=enabled,
        ),
    ):
        return await activity_environment.run(
            materialize_view_activity,
            MaterializeViewInputs(team_id=ateam.pk, dag_id=str(adag.id), node_id=str(anode.id), job_id=str(ajob.id)),
        )


async def _configure(asaved_query, config: dict | None = None) -> None:
    asaved_query.incremental_config = config if config is not None else CONFIG
    await database_sync_to_async(asaved_query.save)(update_fields=["incremental_config"])


@pytest.mark.usefixtures("minio_client")
class TestIncrementalMaterialization:
    async def test_first_run_rebuilds_and_records_a_watermark(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        """With no watermark there is nothing to build on, so the first run is a full refresh —
        which is also the only path that creates the Delta table deltalite later opens."""
        await _configure(asaved_query)

        with _settings(bucket_name):
            result = await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1, DAY2], [10, 20]))

        assert result.row_count == 2
        assert _rows(result.table_uri) == [(DAY1, 10), (DAY2, 20)]

        await database_sync_to_async(asaved_query.refresh_from_db)()
        state = get_incremental_state(asaved_query)
        assert state.last_run_mode == "full_refresh"
        assert state.watermark is not None

        # The runs UI reads the mode off the job to explain what its row count means.
        await database_sync_to_async(ajob.refresh_from_db)()
        assert ajob.run_mode == "full_refresh"

    async def test_second_run_updates_touched_rows_and_leaves_the_rest(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        """The point of the feature: a run rewrites only the keys it returned."""
        await _configure(asaved_query)

        with _settings(bucket_name):
            first = await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1, DAY2], [10, 20]))
            second = await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY2, DAY3], [99, 30]))

        assert _rows(first.table_uri) == [(DAY1, 10), (DAY2, 99), (DAY3, 30)]

        # The returned file list is what the publish copies to S3 for querying. deltalite commits
        # through its own handle, so a handle opened before the upserts would still name the
        # pre-run files here and the published table would silently lose the run's writes.
        live = deltalake.DeltaTable(first.table_uri, storage_options=get_aws_storage_options())
        assert sorted(second.file_uris) == sorted(live.file_uris())

        await database_sync_to_async(asaved_query.refresh_from_db)()
        assert get_incremental_state(asaved_query).last_run_mode == "incremental"

        await database_sync_to_async(ajob.refresh_from_db)()
        assert ajob.run_mode == "incremental"

    async def test_replaying_a_run_does_not_duplicate_rows(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        """Activities retry. If the key match were wrong, a retry would append instead of replace
        and the table would grow a duplicate per run, with nothing failing."""
        await _configure(asaved_query)

        with _settings(bucket_name):
            first = await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1], [10]))
            await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY2], [20]))
            await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY2], [20]))

        assert _rows(first.table_uri) == [(DAY1, 10), (DAY2, 20)]

    async def test_a_recomputed_group_is_replaced_not_added_to(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        """An aggregate must be overwritten, never combined. This is what makes non-associative
        aggregates safe: a bucket is recomputed whole, never merged."""
        await _configure(asaved_query)

        with _settings(bucket_name):
            first = await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1], [10]))
            await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1], [7]))

        assert _rows(first.table_uri) == [(DAY1, 7)]

    async def test_camelcase_columns_survive_an_upsert(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        """delta-rs's MERGE routes through DataFusion, which lowercases identifiers and then fails
        to resolve them. deltalite has no DataFusion and matches column names exactly. Data
        modeling is this codebase's main producer of camelCase columns, and the crate's own suite
        has no mixed-case test, so this is the one pinning it."""
        await _configure(asaved_query)

        with _settings(bucket_name):
            first = await _run(
                activity_environment,
                ateam,
                anode,
                ajob,
                adag,
                _batch([DAY1], [10], value_column="personId"),
                value_column="personId",
            )
            await _run(
                activity_environment,
                ateam,
                anode,
                ajob,
                adag,
                _batch([DAY2], [20], value_column="personId"),
                value_column="personId",
            )

        table = deltalake.DeltaTable(first.table_uri, storage_options=get_aws_storage_options())
        assert "personId" in table.to_pyarrow_table().column_names
        assert _rows(first.table_uri) == [(DAY1, 10), (DAY2, 20)]

    async def test_a_null_unique_key_fails_the_run_instead_of_duplicating(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        """deltalite's keys are NULL-unsafe by design: a null never matches, so the row would be
        inserted every run forever. Failing loudly is the only honest option."""
        await _configure(asaved_query)

        with _settings(bucket_name):
            first = await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1], [10]))

            with pytest.raises(IncrementalWriteError, match="is null"):
                await _run(activity_environment, ateam, anode, ajob, adag, _batch([None], [20]))

        assert _rows(first.table_uri) == [(DAY1, 10)], "the failed run must not have written anything"

    async def test_duplicate_unique_keys_fail_the_run(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        """A duplicate means the declared key does not identify a row. Silently keeping one would
        hide a misconfiguration and drop real data."""
        await _configure(asaved_query)

        with _settings(bucket_name):
            await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1], [10]))

            with pytest.raises(IncrementalWriteError, match="does not identify a single row"):
                await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY2, DAY2], [20, 21]))

    async def test_schema_drift_clears_the_watermark_so_the_next_run_rebuilds(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        """deltalite null-pads a column the batch is missing, overwriting stored values. The query
        text is unchanged here, so the fingerprint cannot catch it — this guard has to."""
        await _configure(asaved_query)

        with _settings(bucket_name):
            await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1], [10]))

            with pytest.raises(IncrementalWriteError):
                await _run(
                    activity_environment,
                    ateam,
                    anode,
                    ajob,
                    adag,
                    _batch([DAY2], [20], value_column="renamed"),
                    value_column="renamed",
                )

        await database_sync_to_async(asaved_query.refresh_from_db)()
        assert get_incremental_state(asaved_query).watermark is None

    async def test_a_definition_change_forces_a_rebuild(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        """Rows built under the old query must not survive alongside rows built under the new one."""
        await _configure(asaved_query)

        with _settings(bucket_name):
            first = await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1], [10]))

            asaved_query.query = {"query": "SELECT 2", "kind": "HogQLQuery"}
            await database_sync_to_async(asaved_query.save)(update_fields=["query"])

            await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY2], [20]))

        assert _rows(first.table_uri) == [(DAY2, 20)], "the rebuild must drop rows from the old definition"

        await database_sync_to_async(asaved_query.refresh_from_db)()
        assert get_incremental_state(asaved_query).last_run_mode == "full_refresh"

    async def test_a_zero_row_window_leaves_the_table_and_watermark_alone(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        """A quiet window is normal, not an error, and must not truncate the table."""
        await _configure(asaved_query)

        with _settings(bucket_name):
            first = await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1], [10]))
            await database_sync_to_async(asaved_query.refresh_from_db)()
            before = get_incremental_state(asaved_query).watermark

            result = await _run(activity_environment, ateam, anode, ajob, adag, _batch([], []))

        assert result.row_count == 0
        assert _rows(first.table_uri) == [(DAY1, 10)]

        await database_sync_to_async(asaved_query.refresh_from_db)()
        assert get_incremental_state(asaved_query).watermark == before

    async def test_flag_off_rebuilds_every_run(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        """The kill switch. With the flag off the behaviour is exactly what ships today."""
        await _configure(asaved_query)

        with _settings(bucket_name):
            first = await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1], [10]), enabled=False)
            await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY2], [20]), enabled=False)

        assert _rows(first.table_uri) == [(DAY2, 20)], "a full refresh replaces the table wholesale"

    async def test_no_config_rebuilds_every_run(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        with _settings(bucket_name):
            first = await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1], [10]))
            await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY2], [20]))

        assert _rows(first.table_uri) == [(DAY2, 20)]

    async def test_multiple_batches_in_one_run_all_land(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        """A run streams ~100MB batches, each its own upsert. Every batch's rows must land."""
        await _configure(asaved_query)

        with _settings(bucket_name):
            first = await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1], [1]))
            result = await _run(
                activity_environment,
                ateam,
                anode,
                ajob,
                adag,
                _batch([DAY2], [20]),
                _batch([DAY3], [30]),
            )

        assert result.row_count == 2
        assert _rows(first.table_uri) == [(DAY1, 1), (DAY2, 20), (DAY3, 30)]

    async def test_a_duplicate_key_across_batches_fails_the_run(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        """A key repeated across batches within one run is the same misconfiguration as within one
        batch, but per-batch upserts would silently turn it into last-write-wins. The offending
        batch must never be written, and the cleared watermark makes the retry rebuild."""
        await _configure(asaved_query)

        with _settings(bucket_name):
            first = await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1], [1]))

            with pytest.raises(IncrementalWriteError, match="does not identify a single row"):
                await _run(
                    activity_environment,
                    ateam,
                    anode,
                    ajob,
                    adag,
                    _batch([DAY2], [20]),
                    _batch([DAY3], [30]),
                    _batch([DAY2], [21]),
                )

        assert _rows(first.table_uri) == [(DAY1, 1), (DAY2, 20), (DAY3, 30)], (
            "the duplicate batch must not have replaced the earlier one"
        )

        await database_sync_to_async(asaved_query.refresh_from_db)()
        assert get_incremental_state(asaved_query).watermark is None

    @pytest.mark.parametrize(
        "batches,match",
        [
            pytest.param((_batch([DAY1, None], [10, 20]),), "is null", id="null_key"),
            pytest.param(
                (_batch([DAY1, DAY1], [10, 11]),),
                "does not identify a single row",
                id="duplicate_within_a_batch",
            ),
            pytest.param(
                (_batch([DAY1], [10]), _batch([DAY1], [11])),
                "does not identify a single row",
                id="duplicate_across_batches",
            ),
        ],
    )
    async def test_the_first_run_enforces_the_unique_key(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag, batches, match
    ):
        """The seeding full refresh must fail on a null or duplicate key too — a table born in
        violation of the contract would poison every later upsert."""
        await _configure(asaved_query)

        with _settings(bucket_name):
            with pytest.raises(IncrementalWriteError, match=match):
                await _run(activity_environment, ateam, anode, ajob, adag, *batches)

        await database_sync_to_async(asaved_query.refresh_from_db)()
        assert get_incremental_state(asaved_query).watermark is None

    async def test_lookback_shifts_the_second_runs_window(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        """The watermark is persisted as an ISO string; the lookback has to apply to the
        deserialized datetime, or every run silently ignores it and misses late-arriving rows."""
        await _configure(asaved_query, {**CONFIG, "lookback_seconds": 3600})
        windows: list[Any] = []

        with _settings(bucket_name):
            await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1, DAY2], [10, 20]), windows=windows)
            await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY3], [30]), windows=windows)

        assert windows[0] is None, "the first run is a full refresh with no window"
        assert windows[1] is not None
        assert windows[1].since == DAY2 - timedelta(seconds=3600)


class _RecordingProducer:
    """Stands in for CDPProducer, recording what a run handed it."""

    def __init__(
        self, *, gate: bool = True, fail_on_chunk: int | None = None, cancel_on_chunk: int | None = None
    ) -> None:
        self._gate = gate
        self._fail_on_chunk = fail_on_chunk
        self._cancel_on_chunk = cancel_on_chunk
        self.staged: list[tuple[Any, Any]] = []
        self.clears = 0

    async def should_run(self) -> bool:
        return self._gate

    async def clear(self) -> None:
        self.clears += 1
        self.staged.clear()

    async def stage_chunk(self, chunk: int, batch: Any) -> None:
        if chunk == self._fail_on_chunk:
            raise RuntimeError("s3 is having a day")
        if chunk == self._cancel_on_chunk:
            # What a Temporal activity cancellation looks like from inside: the SDK cancels the
            # asyncio task, which raises this at the next await point, here.
            raise asyncio.CancelledError()
        self.staged.append((chunk, batch))

    def staged_rows(self) -> list[tuple[Any, Any]]:
        pairs: list[tuple[Any, Any]] = []
        for _, batch in self.staged:
            value_column = next(name for name in batch.schema.names if name != "day")
            pairs.extend(zip(batch.column("day").to_pylist(), batch.column(value_column).to_pylist()))
        return sorted(pairs, key=lambda pair: (pair[0] is None, pair[0]))


def _patch_producer(producer: _RecordingProducer):
    return unittest.mock.patch(
        "posthog.temporal.data_modeling.activities.materialize_view.CDPProducer.for_view",
        return_value=producer,
    )


@pytest.mark.usefixtures("minio_client")
class TestCDPRowStaging:
    """What a run hands to the CDP producer, which is what its subscribed destinations and
    workflows end up running on."""

    async def test_nothing_is_staged_when_nothing_subscribes(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        # The gate is the only thing standing between an unsubscribed view and an S3 write per
        # batch, on every run, forever.
        producer = _RecordingProducer(gate=False)
        await _configure(asaved_query)

        with _settings(bucket_name), _patch_producer(producer):
            result = await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1, DAY2], [10, 20]))

        assert producer.staged == []
        assert producer.clears == 0
        assert result.should_trigger_cdp_producer is False

    async def test_a_full_refresh_stages_the_whole_table(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        producer = _RecordingProducer()
        await _configure(asaved_query)

        with _settings(bucket_name), _patch_producer(producer):
            result = await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1, DAY2], [10, 20]))

        assert producer.staged_rows() == [(DAY1, 10), (DAY2, 20)]
        assert result.should_trigger_cdp_producer is True

    async def test_an_incremental_run_stages_only_its_window(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        # The point of the whole feature: a destination hears about the rows that changed, not
        # every row the view holds.
        await _configure(asaved_query)

        with _settings(bucket_name):
            seed = _RecordingProducer()
            with _patch_producer(seed):
                await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1, DAY2], [10, 20]))

            incremental = _RecordingProducer()
            with _patch_producer(incremental):
                result = await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY3], [30]))

        assert result.incremental is True
        assert incremental.staged_rows() == [(DAY3, 30)]

    async def test_a_staging_failure_discards_the_run_and_leaves_the_view_materialized(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        # Half a run's rows reaching a destination is worse than none, and the materialization is
        # the product either way.
        producer = _RecordingProducer(fail_on_chunk=1)
        await _configure(asaved_query)

        with _settings(bucket_name), _patch_producer(producer):
            result = await _run(
                activity_environment, ateam, anode, ajob, adag, _batch([DAY1], [10]), _batch([DAY2], [20])
            )

        assert result.row_count == 2
        assert _rows(result.table_uri) == [(DAY1, 10), (DAY2, 20)]
        assert result.should_trigger_cdp_producer is False
        assert producer.staged == []
        assert producer.clears >= 2, "the prefix is cleared at the start of the run and again on failure"

    async def test_a_cancellation_mid_stage_discards_the_run(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        # A Temporal activity cancellation raises asyncio.CancelledError, a BaseException rather than
        # an Exception - the same discard-on-first-failure rule must still run, or a cancelled run
        # after staging began leaks its chunks under a prefix no later run's own clear reaches.
        producer = _RecordingProducer(cancel_on_chunk=1)
        await _configure(asaved_query)

        with _settings(bucket_name), _patch_producer(producer):
            with pytest.raises(asyncio.CancelledError):
                await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1], [10]), _batch([DAY2], [20]))

        assert producer.staged == []
        assert producer.clears >= 2, "the prefix is cleared at the start of the run and again on cancellation"

    async def test_a_cancellation_after_the_write_loop_discards_the_run(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        # A cancellation doesn't only land mid-write. The logging, heartbeat teardown, and
        # quality-audit lookup between the last write and the MaterializeViewResult being built are
        # await points too, and the run hasn't handed back a result for the workflow to key its own
        # cleanup off until it actually returns one. This simulates the audit lookup being the point
        # that gets cancelled, after every row has already been staged successfully.
        producer = _RecordingProducer()
        await _configure(asaved_query)

        with _settings(bucket_name), _patch_producer(producer):
            with unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view.data_quality_facade.quality_audit_mode",
                side_effect=asyncio.CancelledError(),
            ):
                with pytest.raises(asyncio.CancelledError):
                    await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1], [10]))

        assert producer.staged == []
        assert producer.clears >= 2, "the prefix is cleared at the start of the run and again on cancellation"

    async def test_a_failed_run_stages_nothing(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        # A run that never lands its rows must not announce them either.
        producer = _RecordingProducer()
        await _configure(asaved_query)

        with _settings(bucket_name), _patch_producer(producer):
            with pytest.raises(IncrementalWriteError):
                await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1, DAY1], [10, 11]))

        assert producer.staged == []
