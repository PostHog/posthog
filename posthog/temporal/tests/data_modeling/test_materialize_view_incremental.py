"""Incremental materialization, exercised against real deltalite and real Delta tables.

Mocked out here: only ``hogql_table`` (so a test controls exactly which rows a "run" returns). The write path itself is real, because every load-bearing unknown lives in the
Rust crate — key matching, duplicate rejection, schema handling, column-name case — and a mock
would assert our idea of deltalite rather than deltalite.
"""

import asyncio
from collections.abc import Callable, Collection
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
import unittest.mock

from django.conf import settings
from django.test import override_settings

import pyarrow as pa
import deltalake

from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import ClickHouseQueryTimeoutError
from posthog.temporal.data_modeling.activities import MaterializeViewInputs, materialize_view_activity
from posthog.temporal.data_modeling.activities.incremental_write import (
    IncrementalWriteError,
    TableUnreadableError,
    UniqueKeyCapError,
)
from posthog.temporal.data_modeling.activities.materialize_view import (
    FAILED_UPDATE_REASON_PREFIX,
    FIRST_BUILD_RESUMED_REASON,
    IncrementalWindow,
    WindowCannotShrinkError,
    get_aws_storage_options,
)

from products.data_modeling.backend.facade.api import get_incremental_state
from products.data_warehouse.backend.facade.api import get_s3_client

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


def _unsigned_batch(day: datetime, count: int, flag: int) -> pa.RecordBatch:
    arrays = cast(
        Collection[pa.Array],
        [
            pa.array([day], type=pa.timestamp("us", tz="UTC")),
            pa.array([count], type=pa.uint64()),
            pa.array([flag], type=pa.uint8()),
        ],
    )
    return pa.RecordBatch.from_arrays(arrays, names=["day", "c", "flag"])


def _rows(table_uri: str) -> list[tuple[Any, Any]]:
    """Stored rows as (day, value), sorted, so tests assert content rather than counts."""
    table = deltalake.DeltaTable(table_uri, storage_options=get_aws_storage_options()).to_pyarrow_table()
    value_column = next(name for name in table.column_names if name != "day")
    pairs = list(zip(table.column("day").to_pylist(), table.column(value_column).to_pylist()))
    return sorted(pairs, key=lambda pair: (pair[0] is None, pair[0]))


def _mock_hogql_table(
    *batches: pa.RecordBatch,
    value_column: str = "c",
    windows: list[Any] | None = None,
    column_types: list[tuple[str, str]] | None = None,
):
    """Stand in for one run: yields the given batches, ignoring the window.

    The window's effect on the generated SQL is covered by the filter-injection tests; what matters
    here is what the write path does with the rows that come back. ``windows`` collects the window
    each run was given, for tests that assert on the computed lower bound.
    """
    # DateTime64 so the activity's arrow transform passes an already-typed timestamp
    # through, the way it does for a real ClickHouse DateTime64 column.
    types = column_types or [("day", "DateTime64(6, 'UTC')"), (value_column, "Int64")]

    def factory(*args, **kwargs):
        if windows is not None:
            windows.append(kwargs.get("window"))
        del args, kwargs

        async def generator():
            for batch in batches:
                yield batch, types

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
    value_column: str = "c",
    windows: list[Any] | None = None,
    column_types: list[tuple[str, str]] | None = None,
):
    with (
        unittest.mock.patch(
            "posthog.temporal.data_modeling.activities.materialize_view.hogql_table",
            _mock_hogql_table(*batches, value_column=value_column, windows=windows, column_types=column_types),
        ),
    ):
        return await activity_environment.run(
            materialize_view_activity,
            MaterializeViewInputs(team_id=ateam.pk, dag_id=str(adag.id), node_id=str(anode.id), job_id=str(ajob.id)),
        )


async def _configure(asaved_query, config: dict | None = None) -> None:
    asaved_query.incremental_config = config if config is not None else CONFIG
    await database_sync_to_async(asaved_query.save)(update_fields=["incremental_config"])


MATERIALIZE_VIEW = "posthog.temporal.data_modeling.activities.materialize_view"
TODAY = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
RECENT_0, RECENT_1, RECENT_2 = (TODAY - timedelta(days=days) for days in (6, 4, 2))
TIMESTAMP_TYPES = [("day", "DateTime64(6, 'UTC')"), ("c", "Int64")]
INTEGER_TYPES = [("day", "Int64"), ("c", "Int64")]

WindowFailure = Callable[[IncrementalWindow], BaseException | None]


def _windowing_enabled():
    return unittest.mock.patch(f"{MATERIALIZE_VIEW}.windowed_materialization_enabled", return_value=True)


def _in_window(key: Any, window: IncrementalWindow | None) -> bool:
    if window is None:
        return True
    if key is None:
        return window.include_null_keys
    return key >= window.since and (window.until is None or key < window.until)


class _WindowedSource:
    def __init__(
        self,
        rows: list[tuple[Any, int]],
        *,
        windows: list[Any],
        integer_keys: bool = False,
        fail: WindowFailure | None = None,
        partial_on_failure: bool = False,
    ) -> None:
        self.rows = rows
        self._windows = windows
        self._fail = fail
        self._partial_on_failure = partial_on_failure
        self._key_type = pa.int64() if integer_keys else pa.timestamp("us", tz="UTC")
        self._types = INTEGER_TYPES if integer_keys else TIMESTAMP_TYPES

    def _batch(self, selected: list[tuple[Any, int]]) -> pa.RecordBatch:
        arrays = cast(
            Collection[pa.Array],
            [
                pa.array([key for key, _ in selected], type=self._key_type),
                pa.array([value for _, value in selected], type=pa.int64()),
            ],
        )
        return pa.RecordBatch.from_arrays(arrays, names=["day", "c"])

    def __call__(self, *args, window: IncrementalWindow | None = None, **kwargs):
        self._windows.append(window)

        async def generator():
            selected = [row for row in self.rows if _in_window(row[0], window)]
            error = self._fail(window) if self._fail is not None and window is not None else None
            if error is not None:
                if self._partial_on_failure and selected:
                    yield self._batch([max(selected, key=lambda row: row[0])]), self._types
                raise error
            yield self._batch(selected), self._types

        return generator()

    async def has_rows(self, *args, since: Any = None, until: Any = None) -> bool:
        return any(
            key is not None and (since is None or key >= since) and (until is None or key < until)
            for key, _ in self.rows
        )

    async def sample_key(self, *args) -> Any:
        return next((key for key, _ in self.rows if key is not None), None)


def _windowed_source(rows: list[tuple[Any, int]], **options: Any) -> _WindowedSource:
    return _WindowedSource(rows, **options)


def _fails_when_window_holds(key: Any, error: BaseException, *, wider_than: Any = None, times: int | None = None):
    failures: list[IncrementalWindow] = []

    def fail(window: IncrementalWindow) -> BaseException | None:
        if not _in_window(key, window) or (times is not None and len(failures) >= times):
            return None
        if wider_than is not None and (window.until is None or window.until - window.since <= wider_than):
            return None
        failures.append(window)
        return error

    return fail


async def _run_windowed(
    activity_environment, ateam, anode, ajob, adag, source: _WindowedSource, key_range: tuple[Any, Any]
):
    with (
        _windowing_enabled(),
        unittest.mock.patch(f"{MATERIALIZE_VIEW}.hogql_table", source),
        unittest.mock.patch(f"{MATERIALIZE_VIEW}._probe_key_range", return_value=key_range),
        unittest.mock.patch(f"{MATERIALIZE_VIEW}._has_rows", source.has_rows),
        unittest.mock.patch(f"{MATERIALIZE_VIEW}._sample_key", source.sample_key),
    ):
        return await activity_environment.run(
            materialize_view_activity,
            MaterializeViewInputs(team_id=ateam.pk, dag_id=str(adag.id), node_id=str(anode.id), job_id=str(ajob.id)),
        )


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
        assert state.has_incremental_history is True

        # The runs UI reads the mode off the job to explain what its row count means.
        await database_sync_to_async(ajob.refresh_from_db)()
        assert ajob.run_mode == "full_refresh"
        assert ajob.full_refresh_reason == "first run"

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
        assert ajob.full_refresh_reason is None

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

    async def test_a_log_that_vanishes_mid_run_clears_the_watermark_so_the_retry_rebuilds(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        """The table opens at the start of the run, then its log is gone when deltalite opens it to
        upsert. Without the watermark cleared, every retry repeats the same failed upsert."""
        await _configure(asaved_query)

        with _settings(bucket_name):
            first = await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1], [10]))

            def remove_log_then_yield(*args, **kwargs):
                async def generator():
                    await asyncio.to_thread(get_s3_client().delete, f"{first.table_uri}/_delta_log", recursive=True)
                    yield _batch([DAY2], [20]), [("day", "DateTime64(6, 'UTC')"), ("c", "Int64")]

                return generator()

            with (
                unittest.mock.patch(
                    "posthog.temporal.data_modeling.activities.materialize_view.hogql_table", remove_log_then_yield
                ),
                pytest.raises(TableUnreadableError),
            ):
                await activity_environment.run(
                    materialize_view_activity,
                    MaterializeViewInputs(
                        team_id=ateam.pk, dag_id=str(adag.id), node_id=str(anode.id), job_id=str(ajob.id)
                    ),
                )

            await database_sync_to_async(asaved_query.refresh_from_db)()
            assert get_incremental_state(asaved_query).watermark is None

            await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1, DAY2], [10, 20]))

        await database_sync_to_async(ajob.refresh_from_db)()
        assert ajob.run_mode == "full_refresh"
        assert _rows(first.table_uri) == [(DAY1, 10), (DAY2, 20)]

    async def test_an_unsigned_column_stays_incremental_across_runs(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        await _configure(asaved_query)
        column_types = [("day", "DateTime64(6, 'UTC')"), ("c", "UInt64"), ("flag", "UInt8")]

        with _settings(bucket_name):
            first = await _run(
                activity_environment, ateam, anode, ajob, adag, _unsigned_batch(DAY1, 10, 1), column_types=column_types
            )
            await _run(
                activity_environment,
                ateam,
                anode,
                ajob,
                adag,
                _unsigned_batch(DAY2, 20, 200),
                column_types=column_types,
            )

        await database_sync_to_async(ajob.refresh_from_db)()
        assert ajob.run_mode == "incremental"
        assert ajob.full_refresh_reason is None

        table = deltalake.DeltaTable(first.table_uri, storage_options=get_aws_storage_options()).to_pyarrow_table()
        stored = sorted(
            zip(table.column("day").to_pylist(), table.column("c").to_pylist(), table.column("flag").to_pylist())
        )
        assert stored == [(DAY1, 10, 1), (DAY2, 20, 200)]

    async def test_a_rebuild_after_a_failed_update_is_not_labelled_a_first_run(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
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

            await _run(
                activity_environment,
                ateam,
                anode,
                ajob,
                adag,
                _batch([DAY2], [20], value_column="renamed"),
                value_column="renamed",
            )

        await database_sync_to_async(ajob.refresh_from_db)()
        assert ajob.run_mode == "full_refresh"
        assert ajob.full_refresh_reason is not None
        assert ajob.full_refresh_reason.startswith(FAILED_UPDATE_REASON_PREFIX)

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

        await database_sync_to_async(ajob.refresh_from_db)()
        assert ajob.full_refresh_reason == "definition changed"

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

    async def test_no_config_rebuilds_every_run(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        windows: list[Any] = []
        with _settings(bucket_name), _windowing_enabled():
            first = await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY1], [10]), windows=windows)
            await _run(activity_environment, ateam, anode, ajob, adag, _batch([DAY2], [20]), windows=windows)

        assert _rows(first.table_uri) == [(DAY2, 20)]
        assert windows == [None, None]

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
        state = get_incremental_state(asaved_query)
        assert state.watermark is None
        assert state.has_incremental_history is True

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
        assert len(windows) == 2
        assert windows[1] is not None
        assert windows[1].since == DAY2 - timedelta(seconds=3600)
        assert windows[1].until is None


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


async def _state(asaved_query):
    await database_sync_to_async(asaved_query.refresh_from_db)()
    return get_incremental_state(asaved_query)


@pytest.mark.usefixtures("minio_client")
class TestWindowedMaterialization:
    async def test_a_first_build_in_windows_lands_every_row_once(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        await _configure(asaved_query, {**CONFIG, "unique_key": ["c"]})
        windows: list[Any] = []
        source = _windowed_source([(RECENT_0, 1), (None, 5), (RECENT_2, 1)], windows=windows)

        with _settings(bucket_name):
            result = await _run_windowed(activity_environment, ateam, anode, ajob, adag, source, (RECENT_0, RECENT_2))

        assert _rows(result.table_uri) == [(RECENT_2, 1), (None, 5)]
        assert len(windows) > 1
        assert windows[0].since <= RECENT_0 and windows[0].include_null_keys
        assert not any(window.include_null_keys for window in windows[1:])
        assert windows[-1].until is None
        state = await _state(asaved_query)
        assert state.watermark == RECENT_2.isoformat()
        assert state.first_build_in_progress is False
        await database_sync_to_async(ajob.refresh_from_db)()
        assert ajob.run_mode == "full_refresh"

    @pytest.mark.parametrize(
        "rows,key_range,failing_key,integer_keys",
        [
            pytest.param(
                [(RECENT_0, 10), (RECENT_1, 20), (RECENT_2, 30)],
                (RECENT_0, RECENT_2),
                RECENT_1,
                False,
                id="datetime_key",
            ),
            pytest.param([(0, 10), (20, 20), (40, 30)], (0, 40), 20, True, id="integer_key"),
        ],
    )
    async def test_a_retry_after_a_failed_window_resumes_from_the_saved_window(
        self,
        activity_environment,
        ateam,
        anode,
        asaved_query,
        ajob,
        bucket_name,
        adag,
        rows,
        key_range,
        failing_key,
        integer_keys,
    ):
        await _configure(asaved_query)
        first_attempt: list[Any] = []
        retry: list[Any] = []
        failing = _windowed_source(
            rows,
            windows=first_attempt,
            integer_keys=integer_keys,
            fail=_fails_when_window_holds(failing_key, RuntimeError("worker restarted")),
        )

        with _settings(bucket_name):
            with pytest.raises(RuntimeError, match="worker restarted"):
                await _run_windowed(activity_environment, ateam, anode, ajob, adag, failing, key_range)
            interrupted = await _state(asaved_query)

            result = await _run_windowed(
                activity_environment,
                ateam,
                anode,
                ajob,
                adag,
                _windowed_source(rows, windows=retry, integer_keys=integer_keys),
                key_range,
            )

        assert interrupted.first_build_in_progress is True
        assert interrupted.watermark == (rows[0][0] if integer_keys else rows[0][0].isoformat())
        assert retry[0].since == rows[0][0]
        assert _rows(result.table_uri) == rows
        finished = await _state(asaved_query)
        assert finished.first_build_in_progress is False
        assert finished.backfill_until is None
        await database_sync_to_async(ajob.refresh_from_db)()
        assert ajob.run_mode == "full_refresh"
        assert ajob.full_refresh_reason == FIRST_BUILD_RESUMED_REASON

    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(ClickHouseQueryTimeoutError("Code: 159. Timeout exceeded"), id="timeout"),
            pytest.param(UniqueKeyCapError("too many unique keys"), id="unique_key_cap"),
        ],
    )
    async def test_an_oversized_window_is_halved_and_the_build_finishes(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag, error
    ):
        await _configure(asaved_query)
        windows: list[Any] = []
        rows = [(RECENT_0, 10), (RECENT_1, 20), (RECENT_2, 30)]
        source = _windowed_source(
            rows,
            windows=windows,
            fail=_fails_when_window_holds(RECENT_1, error, wider_than=timedelta(days=1)),
            partial_on_failure=True,
        )

        with _settings(bucket_name):
            result = await _run_windowed(activity_environment, ateam, anode, ajob, adag, source, (RECENT_0, RECENT_2))

        assert _rows(result.table_uri) == rows
        assert result.row_count == len(rows)
        holding = [window for window in windows if window.until is not None and _in_window(RECENT_1, window)]
        assert holding[-1].until - holding[-1].since <= timedelta(days=1)

    async def test_a_crash_after_a_halved_window_resumes_without_skipping_rows(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        await _configure(asaved_query)
        unwritten = RECENT_0 + timedelta(days=2, hours=5)
        streamed_before_timeout = RECENT_0 + timedelta(days=2, hours=12)
        rows = [(RECENT_0, 10), (unwritten, 20), (streamed_before_timeout, 30), (RECENT_2, 40)]
        failures: list[IncrementalWindow] = []

        def fail(window: IncrementalWindow) -> BaseException | None:
            if not _in_window(unwritten, window) or window.until is None:
                return None
            failures.append(window)
            if len(failures) == 1:
                return ClickHouseQueryTimeoutError("Code: 159. Timeout exceeded")
            return RuntimeError("worker restarted")

        with _settings(bucket_name):
            with pytest.raises(RuntimeError, match="worker restarted"):
                await _run_windowed(
                    activity_environment,
                    ateam,
                    anode,
                    ajob,
                    adag,
                    _windowed_source(rows, windows=[], fail=fail, partial_on_failure=True),
                    (RECENT_0, RECENT_2),
                )
            result = await _run_windowed(
                activity_environment, ateam, anode, ajob, adag, _windowed_source(rows, windows=[]), (RECENT_0, RECENT_2)
            )

        assert _rows(result.table_uri) == rows

    async def test_a_stray_ancient_key_does_not_make_the_build_crawl_through_the_gap(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        await _configure(asaved_query)
        rows = [(datetime(2001, 1, 1, tzinfo=UTC), 1), (RECENT_0, 10), (RECENT_2, 30)]
        windows: list[Any] = []

        with _settings(bucket_name):
            result = await _run_windowed(
                activity_environment,
                ateam,
                anode,
                ajob,
                adag,
                _windowed_source(rows, windows=windows),
                (rows[0][0], RECENT_2),
            )

        assert _rows(result.table_uri) == rows
        assert len(windows) < 40

    async def test_a_window_at_the_minimum_span_fails_without_losing_progress(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        await _configure(asaved_query)
        source = _windowed_source(
            [(RECENT_0, 10), (RECENT_1, 20)],
            windows=[],
            fail=_fails_when_window_holds(RECENT_1, ClickHouseQueryTimeoutError("Code: 159. Timeout exceeded")),
        )

        with _settings(bucket_name):
            with pytest.raises(WindowCannotShrinkError):
                await _run_windowed(activity_environment, ateam, anode, ajob, adag, source, (RECENT_0, RECENT_1))

        state = await _state(asaved_query)
        assert state.watermark == RECENT_0.isoformat()

    async def test_a_key_the_filter_cannot_push_down_builds_in_one_query(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        asaved_query.query = {
            "kind": "HogQLQuery",
            "query": "WITH daily AS (SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events GROUP BY day) "
            "SELECT day, c FROM daily",
        }
        await database_sync_to_async(asaved_query.save)(update_fields=["query"])
        await _configure(asaved_query)
        windows: list[Any] = []

        with _settings(bucket_name):
            await _run_windowed(
                activity_environment,
                ateam,
                anode,
                ajob,
                adag,
                _windowed_source([(RECENT_0, 10), (RECENT_2, 30)], windows=windows),
                (RECENT_0, RECENT_2),
            )

        assert windows == [None]

    async def test_a_run_that_fits_one_window_issues_one_unbounded_query(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        await _configure(asaved_query)
        recent = datetime.now(UTC) - timedelta(hours=6)
        windows: list[Any] = []

        with _settings(bucket_name):
            await _run(activity_environment, ateam, anode, ajob, adag, _batch([recent], [10]))
            await _run_windowed(
                activity_environment,
                ateam,
                anode,
                ajob,
                adag,
                _windowed_source([(recent, 10)], windows=windows),
                (recent, recent),
            )

        assert len(windows) == 1
        assert windows[0].until is None

    async def test_a_cdp_view_checkpoints_only_at_the_end_and_stages_each_row_once(
        self, activity_environment, ateam, anode, asaved_query, ajob, bucket_name, adag
    ):
        await _configure(asaved_query)
        rows = [(RECENT_0, 10), (RECENT_1, 20), (RECENT_2, 30)]

        with _settings(bucket_name):
            with _patch_producer(_RecordingProducer()), pytest.raises(RuntimeError, match="worker restarted"):
                await _run_windowed(
                    activity_environment,
                    ateam,
                    anode,
                    ajob,
                    adag,
                    _windowed_source(
                        rows, windows=[], fail=_fails_when_window_holds(RECENT_2, RuntimeError("worker restarted"))
                    ),
                    (RECENT_0, RECENT_2),
                )
            interrupted = await _state(asaved_query)

            producer = _RecordingProducer()
            with _patch_producer(producer):
                await _run_windowed(
                    activity_environment,
                    ateam,
                    anode,
                    ajob,
                    adag,
                    _windowed_source(
                        rows,
                        windows=[],
                        fail=_fails_when_window_holds(
                            RECENT_1,
                            ClickHouseQueryTimeoutError("Code: 159. Timeout exceeded"),
                            wider_than=timedelta(days=1),
                            times=1,
                        ),
                    ),
                    (RECENT_0, RECENT_2),
                )

        assert interrupted.watermark is None
        assert producer.staged_rows() == rows
