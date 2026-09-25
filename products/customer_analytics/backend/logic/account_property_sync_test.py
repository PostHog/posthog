from collections.abc import AsyncIterator
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.apps import apps

import pyarrow as pa
import pyarrow.parquet as pq
from asgiref.sync import async_to_sync

from products.customer_analytics.backend.logic import account_property_sync as aps
from products.customer_analytics.backend.logic.account_property_runs import (
    AccountPropertySyncRunContext,
    start_account_property_sync_runs,
)
from products.customer_analytics.backend.logic.account_property_sync import (
    AccountPropertySyncPhase,
    AccountPropertySyncSegment,
    AppliedSourceValues,
    _iter_parquet_row_batches,
    _list_snapshot_files,
    _mark_completed_and_maybe_cleanup,
    _matching_account_ids,
    _merge_snapshot_files,
    _read_snapshot_hashes,
    _source_values,
    _value_hash,
    _write_snapshot_hashes,
    run_account_property_segment_sync,
)
from products.customer_analytics.backend.models import CustomPropertySource, CustomPropertySyncRun
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin
from products.customer_analytics.backend.test.factories import create_account, create_custom_property_definition
from products.warehouse_sources.backend.facade.hooks import saved_query_binding
from products.warehouse_sources.backend.facade.temporal import (
    account_property_job_staged_prefix,
    account_property_snapshot_prefix,
)

_MODULE = "products.customer_analytics.backend.logic.account_property_sync"
DataWarehouseSavedQuery = apps.get_model("data_modeling", "DataWarehouseSavedQuery")


class AccountPropertySegmentTest(TeamScopedTestMixin, BaseTest):
    def _create_source(self) -> CustomPropertySource:
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="accounts",
            columns={"external_id": {}, "plan": {}},
        )
        definition = create_custom_property_definition(team_id=self.team.id, name="Plan")
        return CustomPropertySource.objects.create(
            team=self.team,
            definition=definition,
            saved_query=saved_query,
            key_column="external_id",
            source_column="plan",
        )

    def test_segments_tracked_and_ignored_accounts_and_excludes_churned_accounts(self) -> None:
        tracked = create_account(team_id=self.team.id, external_id="tracked")
        ignored = create_account(team_id=self.team.id, external_id="ignored", ignored_at=datetime.now(UTC))
        create_account(team_id=self.team.id, external_id="churned", churned_at=datetime.now(UTC))

        tracked_matches = _matching_account_ids(
            self.team.id,
            AccountPropertySyncSegment.TRACKED,
            ["tracked", "ignored", "churned"],
        )
        ignored_matches = _matching_account_ids(
            self.team.id,
            AccountPropertySyncSegment.IGNORED,
            ["tracked", "ignored", "churned"],
        )

        assert tracked_matches == {"tracked": tracked.id}
        assert ignored_matches == {"ignored": ignored.id}

    def test_value_hash_is_stable_for_equivalent_values(self) -> None:
        assert _value_hash({"a": 1, "b": [2, 3]}) == _value_hash({"b": [2, 3], "a": 1})

    def test_segment_sync_persists_source_run_counts(self) -> None:
        source = self._create_source()
        start_account_property_sync_runs(
            AccountPropertySyncRunContext(
                team_id=self.team.id,
                saved_query_id=str(source.saved_query_id),
                job_id="job-1",
            ),
            workflow_id="stage-workflow-job-1",
            workflow_run_id="00000000-0000-4000-8000-000000000001",
        )

        async def batches(*args):
            yield [{"external_id": "acme", "plan": "enterprise"}]

        with (
            patch(f"{_MODULE}._segment_already_completed", new=AsyncMock(return_value=False)),
            patch(f"{_MODULE}._enabled_sources", return_value=[source]),
            patch(f"{_MODULE}._read_snapshot_hashes", new=AsyncMock(return_value={})),
            patch(f"{_MODULE}._iter_parquet_row_batches", side_effect=batches),
            patch(f"{_MODULE}._matching_account_ids", return_value={"acme": uuid4()}),
            patch(
                f"{_MODULE}._apply_source_values",
                return_value=AppliedSourceValues(written=1, hashes={"acme": "hash"}, failed=False),
            ),
            patch(f"{_MODULE}._write_snapshot_hashes", new=AsyncMock()),
            patch(f"{_MODULE}._mark_completed_and_maybe_cleanup", new=AsyncMock()),
        ):
            async_to_sync(run_account_property_segment_sync)(
                team_id=self.team.id,
                binding=saved_query_binding(str(source.saved_query_id)),
                job_id="job-1",
                segment=AccountPropertySyncSegment.TRACKED,
            )

        run = CustomPropertySyncRun.objects.for_team(self.team.id).get(source=source, segment="tracked")
        assert (run.status, run.phase) == ("completed", "completed")
        assert (run.rows_read, run.changed, run.existing, run.produced) == (1, 1, 1, 1)

    def test_segment_sync_completes_when_snapshot_file_disappears_after_listing(self) -> None:
        source = self._create_source()
        source.consecutive_failures = 4
        source.save(update_fields=["consecutive_failures"])
        start_account_property_sync_runs(
            AccountPropertySyncRunContext(
                team_id=self.team.id,
                saved_query_id=str(source.saved_query_id),
                job_id="job-1",
            ),
            workflow_id="stage-workflow-job-1",
            workflow_run_id="00000000-0000-4000-8000-000000000001",
        )
        client = MagicMock()
        client._ls = AsyncMock(return_value=[{"Key": "prefix/deleted.parquet", "type": "file"}])
        client._cat_file = AsyncMock(side_effect=FileNotFoundError())

        async def no_batches(*args: object) -> AsyncIterator[list[dict[str, Any]]]:
            for _ in range(0):
                yield []

        with (
            patch(f"{_MODULE}._segment_already_completed", new=AsyncMock(return_value=False)),
            patch(f"{_MODULE}._enabled_sources", return_value=[source]),
            patch(f"{_MODULE}.aget_s3_client", return_value=_S3ClientContext(client)),
            patch(f"{_MODULE}._iter_parquet_row_batches", side_effect=no_batches),
            patch(f"{_MODULE}._mark_completed_and_maybe_cleanup", new=AsyncMock()),
        ):
            async_to_sync(run_account_property_segment_sync)(
                team_id=self.team.id,
                binding=saved_query_binding(str(source.saved_query_id)),
                job_id="job-1",
                segment=AccountPropertySyncSegment.TRACKED,
                final_attempt=True,
            )

        run = CustomPropertySyncRun.objects.for_team(self.team.id).get(source=source, segment="tracked")
        source.refresh_from_db()
        assert run.status == "completed"
        assert source.consecutive_failures == 4
        assert source.is_enabled

    def test_final_attempt_persists_a_failed_run(self) -> None:
        source = self._create_source()
        start_account_property_sync_runs(
            AccountPropertySyncRunContext(
                team_id=self.team.id,
                saved_query_id=str(source.saved_query_id),
                job_id="job-1",
            ),
            workflow_id="stage-workflow-job-1",
            workflow_run_id="00000000-0000-4000-8000-000000000001",
        )

        with (
            patch(f"{_MODULE}._segment_already_completed", new=AsyncMock(return_value=False)),
            patch(f"{_MODULE}._enabled_sources", return_value=[source]),
            patch(f"{_MODULE}._read_snapshot_hashes", new=AsyncMock(side_effect=OSError("S3 unavailable"))),
        ):
            with pytest.raises(OSError, match="S3 unavailable"):
                async_to_sync(run_account_property_segment_sync)(
                    team_id=self.team.id,
                    binding=saved_query_binding(str(source.saved_query_id)),
                    job_id="job-1",
                    segment=AccountPropertySyncSegment.IGNORED,
                    final_attempt=True,
                )

        run = CustomPropertySyncRun.objects.for_team(self.team.id).get(source=source, segment="ignored")
        assert run.status == "failed"
        assert run.finished_at is not None

    def test_final_attempt_finishes_runs_when_source_loading_fails(self) -> None:
        source = self._create_source()
        start_account_property_sync_runs(
            AccountPropertySyncRunContext(
                team_id=self.team.id,
                saved_query_id=str(source.saved_query_id),
                job_id="job-1",
            ),
            workflow_id="stage-workflow-job-1",
            workflow_run_id="00000000-0000-4000-8000-000000000001",
        )

        with (
            patch(f"{_MODULE}._segment_already_completed", new=AsyncMock(return_value=False)),
            patch(f"{_MODULE}._enabled_sources", side_effect=OSError("database unavailable")),
            pytest.raises(OSError, match="database unavailable"),
        ):
            async_to_sync(run_account_property_segment_sync)(
                team_id=self.team.id,
                binding=saved_query_binding(str(source.saved_query_id)),
                job_id="job-1",
                segment=AccountPropertySyncSegment.TRACKED,
                final_attempt=True,
            )

        run = CustomPropertySyncRun.objects.for_team(self.team.id).get(source=source, segment="tracked")
        assert run.status == "failed"
        assert run.finished_at is not None

    def test_disabled_source_run_finishes_without_work(self) -> None:
        source = self._create_source()
        start_account_property_sync_runs(
            AccountPropertySyncRunContext(
                team_id=self.team.id,
                saved_query_id=str(source.saved_query_id),
                job_id="job-1",
            ),
            workflow_id="stage-workflow-job-1",
            workflow_run_id="00000000-0000-4000-8000-000000000001",
        )
        source.is_enabled = False
        source.save(update_fields=["is_enabled"])

        async def no_batches(*args):
            for _ in range(0):
                yield []

        with (
            patch(f"{_MODULE}._segment_already_completed", new=AsyncMock(return_value=False)),
            patch(f"{_MODULE}._enabled_sources", return_value=[]),
            patch(f"{_MODULE}._iter_parquet_row_batches", side_effect=no_batches),
            patch(f"{_MODULE}._mark_completed_and_maybe_cleanup", new=AsyncMock()),
        ):
            async_to_sync(run_account_property_segment_sync)(
                team_id=self.team.id,
                binding=saved_query_binding(str(source.saved_query_id)),
                job_id="job-1",
                segment=AccountPropertySyncSegment.TRACKED,
            )

        run = CustomPropertySyncRun.objects.for_team(self.team.id).get(source=source, segment="tracked")
        assert run.status == "completed"
        assert run.finished_at is not None


_T = TypeVar("_T")


class _S3ClientContext(Generic[_T]):
    def __init__(self, client: _T) -> None:
        self.client = client

    async def __aenter__(self) -> _T:
        return self.client

    async def __aexit__(self, *args: object) -> bool:
        return False


@pytest.mark.parametrize(
    "rows, expected",
    [
        ([{"external_id": "org-1", "plan": None}], {"org-1": None}),
        ([{"external_id": "org-1", "plan": 0}], {"org-1": 0}),
        ([{"external_id": "org-1", "plan": False}], {"org-1": False}),
        ([{"external_id": "org-1", "plan": ""}], {"org-1": ""}),
        ([{"external_id": "org-1"}], {}),
        ([{"plan": None}], {}),
        ([{"external_id": None, "plan": None}], {}),
        ([], {}),
        (
            [{"external_id": "org-1", "plan": "silver"}, {"external_id": "org-1", "plan": None}],
            {"org-1": None},
        ),
    ],
)
def test_source_values_preserve_explicit_nulls_but_skip_missing_columns(rows, expected) -> None:
    assert _source_values(rows, "external_id", "plan") == expected


@pytest.mark.asyncio
async def test_each_staged_batch_is_shared_across_sources() -> None:
    binding = saved_query_binding("019f0000-0000-7000-8000-000000000001")
    sources = []
    for index in range(2):
        source = MagicMock()
        source.id = f"source-{index}"
        source.key_column = "organization_id"
        source.source_column = f"value_{index}"
        sources.append(source)
    batch_calls = 0

    async def batches(*args):
        nonlocal batch_calls
        batch_calls += 1
        yield [{"organization_id": "org-1", "value_0": 1, "value_1": 2}]

    with (
        patch(f"{_MODULE}._segment_already_completed", new=AsyncMock(return_value=False)),
        patch(f"{_MODULE}._enabled_sources", return_value=sources),
        patch(f"{_MODULE}._read_snapshot_hashes", new=AsyncMock(return_value={})),
        patch(f"{_MODULE}.finish_account_property_sync_runs"),
        patch(f"{_MODULE}.finalize_account_property_sync_runs"),
        patch(f"{_MODULE}._iter_parquet_row_batches", side_effect=batches),
        patch(f"{_MODULE}._matching_account_ids", return_value={}),
        patch(f"{_MODULE}._write_snapshot_hashes", new=AsyncMock()),
        patch(f"{_MODULE}._mark_completed_and_maybe_cleanup", new=AsyncMock()),
    ):
        await run_account_property_segment_sync(
            team_id=7,
            binding=binding,
            job_id="job-1",
            segment=AccountPropertySyncSegment.TRACKED,
        )

    assert batch_calls == 1


@pytest.mark.asyncio
async def test_sync_records_each_phase_duration() -> None:
    binding = saved_query_binding("019f0000-0000-7000-8000-000000000001")
    source = MagicMock()
    source.id = "source-1"
    source.key_column = "organization_id"
    source.source_column = "value"
    phase_duration_recorder = MagicMock()

    async def batches(*args):
        yield [{"organization_id": "org-1", "value": 1}]

    with (
        patch(f"{_MODULE}._segment_already_completed", new=AsyncMock(return_value=False)),
        patch(f"{_MODULE}._enabled_sources", return_value=[source]),
        patch(f"{_MODULE}._read_snapshot_hashes", new=AsyncMock(return_value={})),
        patch(f"{_MODULE}._iter_parquet_row_batches", side_effect=batches),
        patch(f"{_MODULE}._matching_account_ids", return_value={"org-1": MagicMock()}),
        patch(
            f"{_MODULE}._apply_source_values",
            return_value=AppliedSourceValues(written=1, hashes={"org-1": "hash"}, failed=False),
        ),
        patch(f"{_MODULE}._write_snapshot_hashes", new=AsyncMock()),
        patch(f"{_MODULE}._mark_completed_and_maybe_cleanup", new=AsyncMock()),
        patch(f"{_MODULE}.finish_account_property_sync_runs"),
        patch(f"{_MODULE}.finalize_account_property_sync_runs"),
        patch(f"{_MODULE}.record_account_property_sync_phase_duration", phase_duration_recorder),
    ):
        await run_account_property_segment_sync(
            team_id=7,
            binding=binding,
            job_id="job-1",
            segment=AccountPropertySyncSegment.TRACKED,
        )

    assert [call.kwargs["phase"] for call in phase_duration_recorder.call_args_list] == [
        phase.value for phase in AccountPropertySyncPhase
    ]


@pytest.mark.asyncio
async def test_staged_parquet_is_decoded_in_bounded_batches() -> None:
    binding = saved_query_binding("019f0000-0000-7000-8000-000000000001")
    table = pa.table({"organization_id": [f"org-{index}" for index in range(50_001)]})
    buffer = pa.BufferOutputStream()
    pq.write_table(table, buffer)
    client = MagicMock()
    client._ls = AsyncMock(return_value=[{"Key": "prefix/chunk.parquet", "type": "file"}])
    client._cat_file = AsyncMock(return_value=buffer.getvalue().to_pybytes())

    with patch(f"{_MODULE}.aget_s3_client", return_value=_S3ClientContext(client)):
        batch_sizes = [
            len(rows)
            async for rows in _iter_parquet_row_batches(
                7,
                binding,
                "job-1",
            )
        ]

    assert batch_sizes == [50_000, 1]


@pytest.mark.asyncio
async def test_staged_parquet_is_deleted_only_after_both_segments_complete() -> None:
    binding = saved_query_binding("019f0000-0000-7000-8000-000000000001")
    client = MagicMock()
    client._pipe_file = AsyncMock()
    client._rm = AsyncMock()
    client._ls = AsyncMock(
        side_effect=[
            [{"Key": "prefix/tracked.done", "type": "file"}],
            [
                {"Key": "prefix/tracked.done", "type": "file"},
                {"Key": "prefix/ignored.done", "type": "file"},
            ],
        ]
    )

    with patch(f"{_MODULE}.aget_s3_client", return_value=_S3ClientContext(client)):
        await _mark_completed_and_maybe_cleanup(7, binding, "job-1", AccountPropertySyncSegment.TRACKED)
        client._rm.assert_not_awaited()
        await _mark_completed_and_maybe_cleanup(7, binding, "job-1", AccountPropertySyncSegment.IGNORED)

    client._rm.assert_awaited_once_with(
        f"s3://{account_property_job_staged_prefix(7, binding, 'job-1')}/",
        recursive=True,
    )


class _FakeS3:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.times: dict[str, int] = {}
        self._clock = 0

    async def _ls(self, path: str, *, detail: bool = True) -> list[dict[str, Any]]:
        del detail
        prefix = aps._s3_key(path).rstrip("/") + "/"
        entries = [
            {"Key": key, "type": "file", "LastModified": self.times[key]}
            for key in self.store
            if key.startswith(prefix)
        ]
        if not entries:
            raise FileNotFoundError(path)
        return entries

    async def _cat_file(self, path: str) -> bytes:
        key = aps._s3_key(path)
        if key not in self.store:
            raise FileNotFoundError(path)
        return self.store[key]

    async def _pipe_file(self, path: str, data: bytes) -> None:
        self._clock += 1
        key = aps._s3_key(path)
        self.store[key] = data
        self.times[key] = self._clock

    async def _rm(self, paths: str | list[str], *, recursive: bool = False) -> None:
        del recursive
        for path in [paths] if isinstance(paths, str) else paths:
            key = aps._s3_key(path)
            self.store.pop(key, None)
            self.times.pop(key, None)


def _fake_s3_patch(fake: _FakeS3) -> AbstractContextManager[object]:
    return patch(f"{_MODULE}.aget_s3_client", lambda: _S3ClientContext(fake))


_SNAPSHOT_BINDING = saved_query_binding("019f0000-0000-7000-8000-000000000002")
_SEGMENT = AccountPropertySyncSegment.TRACKED


async def _write(fake: _FakeS3, job_id: str, hashes: dict[str, str]) -> None:
    with _fake_s3_patch(fake):
        await _write_snapshot_hashes(7, _SNAPSHOT_BINDING, "src", _SEGMENT, job_id, hashes)


async def _read(fake: _FakeS3) -> dict[str, str]:
    with _fake_s3_patch(fake):
        return await _read_snapshot_hashes(7, _SNAPSHOT_BINDING, "src", _SEGMENT)


@pytest.mark.asyncio
async def test_snapshot_files_without_timestamps_merge_before_dated_files() -> None:
    client = MagicMock()
    client._ls = AsyncMock(
        return_value=[
            {"Key": "prefix/dated-new.parquet", "type": "file", "LastModified": datetime(2026, 1, 2, tzinfo=UTC)},
            {"Key": "prefix/undated.parquet", "type": "file"},
            {"Key": "prefix/dated-old.parquet", "type": "file", "LastModified": datetime(2026, 1, 1, tzinfo=UTC)},
        ]
    )

    files = await _list_snapshot_files(client, "prefix")

    assert files == ["prefix/undated.parquet", "prefix/dated-old.parquet", "prefix/dated-new.parquet"]


@pytest.mark.asyncio
async def test_snapshot_write_compacts_prior_files_newest_hash_winning() -> None:
    fake = _FakeS3()
    await _write(fake, "job-1", {"a": "h1", "b": "h1"})
    await _write(fake, "job-2", {"b": "h2", "c": "h2"})

    assert len(fake.store) == 1
    assert await _read(fake) == {"a": "h1", "b": "h2", "c": "h2"}


@pytest.mark.asyncio
async def test_snapshot_read_skips_file_deleted_by_concurrent_compaction() -> None:
    fake = _FakeS3()
    await _write(fake, "job-1", {"a": "h1"})
    prefix = account_property_snapshot_prefix(7, _SNAPSHOT_BINDING, "src", _SEGMENT.value)
    listed = await _list_snapshot_files(fake, prefix)
    await fake._rm(listed)

    merge = await _merge_snapshot_files(fake, listed)

    assert merge.hashes == {}
    assert not merge.complete


@pytest.mark.asyncio
async def test_snapshot_read_discards_partial_hashes_when_a_newer_file_disappears() -> None:
    fake = _FakeS3()
    prefix = account_property_snapshot_prefix(7, _SNAPSHOT_BINDING, "src", _SEGMENT.value)
    await fake._pipe_file(f"{prefix}/job-1.parquet", aps._encode_snapshot({"account": "old"}))
    await fake._pipe_file(f"{prefix}/job-2.parquet", aps._encode_snapshot({"account": "new"}))
    original_cat_file = fake._cat_file

    async def _cat_with_missing_newer_file(path: str) -> bytes:
        if path.endswith("/job-2.parquet"):
            raise FileNotFoundError(path)
        return await original_cat_file(path)

    with patch.object(fake, "_cat_file", _cat_with_missing_newer_file):
        hashes = await _read(fake)

    assert hashes == {}


@pytest.mark.asyncio
async def test_snapshot_write_persists_only_current_hashes_after_an_incomplete_merge() -> None:
    fake = _FakeS3()
    prefix = account_property_snapshot_prefix(7, _SNAPSHOT_BINDING, "src", _SEGMENT.value)
    job_1 = f"{prefix}/job-1.parquet"
    job_2 = f"{prefix}/job-2.parquet"
    replacement = f"{prefix}/concurrent.parquet"
    await fake._pipe_file(job_1, aps._encode_snapshot({"account": "old"}))
    await fake._pipe_file(job_2, aps._encode_snapshot({"account": "new"}))
    original_cat_file = fake._cat_file

    async def _cat_then_compact(path: str) -> bytes:
        data = await original_cat_file(path)
        if path.endswith("/job-1.parquet"):
            await fake._pipe_file(replacement, aps._encode_snapshot({"account": "new"}))
            await fake._rm([job_1, job_2])
        return data

    with patch.object(fake, "_cat_file", _cat_then_compact):
        await _write(fake, "job-3", {"other": "value"})

    assert f"{prefix}/job-3.parquet" in fake.store
    assert await _read(fake) == {"account": "new", "other": "value"}


@pytest.mark.asyncio
async def test_snapshot_cleanup_retries_files_after_batch_delete_race() -> None:
    fake = _FakeS3()
    prefix = account_property_snapshot_prefix(7, _SNAPSHOT_BINDING, "src", _SEGMENT.value)
    await fake._pipe_file(f"{prefix}/job-1.parquet", aps._encode_snapshot({"a": "h1"}))
    await fake._pipe_file(f"{prefix}/job-2.parquet", aps._encode_snapshot({"b": "h2"}))
    original_rm = fake._rm
    batch_failed = False

    async def _rm_with_batch_race(paths: str | list[str], *, recursive: bool = False) -> None:
        nonlocal batch_failed
        if isinstance(paths, list) and not batch_failed:
            batch_failed = True
            raise FileNotFoundError(paths[0])
        await original_rm(paths, recursive=recursive)

    with patch.object(fake, "_rm", _rm_with_batch_race):
        await _write(fake, "job-3", {"c": "h3"})

    assert set(fake.store) == {f"{prefix}/job-3.parquet"}
    assert await _read(fake) == {"a": "h1", "b": "h2", "c": "h3"}


@pytest.mark.asyncio
async def test_snapshot_read_propagates_non_missing_file_errors() -> None:
    fake = _FakeS3()
    await _write(fake, "job-1", {"a": "h1"})

    async def _raise_s3_error(path: str) -> bytes:
        raise OSError(f"S3 unavailable: {path}")

    with patch.object(fake, "_cat_file", _raise_s3_error), pytest.raises(OSError, match="S3 unavailable"):
        await _read(fake)
