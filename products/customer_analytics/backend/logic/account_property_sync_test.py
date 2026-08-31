from datetime import UTC, datetime
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.apps import apps

import pyarrow as pa
import pyarrow.parquet as pq
from asgiref.sync import async_to_sync

from products.customer_analytics.backend.logic.account_property_runs import (
    AccountPropertySyncRunContext,
    start_account_property_sync_runs,
)
from products.customer_analytics.backend.logic.account_property_sync import (
    AccountPropertySyncPhase,
    AccountPropertySyncSegment,
    AppliedSourceValues,
    _iter_parquet_row_batches,
    _mark_completed_and_maybe_cleanup,
    _matching_account_ids,
    _value_hash,
    run_account_property_segment_sync,
)
from products.customer_analytics.backend.models import CustomPropertySource, CustomPropertySyncRun
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin
from products.customer_analytics.backend.test.factories import create_account, create_custom_property_definition
from products.warehouse_sources.backend.facade.hooks import saved_query_binding
from products.warehouse_sources.backend.facade.temporal import account_property_job_staged_prefix

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


class _S3ClientContext:
    def __init__(self, client: MagicMock) -> None:
        self.client = client

    async def __aenter__(self) -> MagicMock:
        return self.client

    async def __aexit__(self, *args) -> bool:
        return False


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
