import io
import hashlib
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractContextManager, ExitStack
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Generic, TypeVar
from uuid import UUID, uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.apps import apps

import pyarrow as pa
import pyarrow.parquet as pq
from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.dataclasses import frozen
from posthog.models import Team

from products.customer_analytics.backend.logic import account_property_sync as aps
from products.customer_analytics.backend.logic.account_property_runs import (
    AccountPropertySyncRunContext,
    AccountPropertySyncSegmentIncompleteError,
    start_account_property_sync_runs,
)
from products.customer_analytics.backend.logic.account_property_sync import (
    AccountPropertySourceRejectedError,
    AccountPropertySourceValueError,
    AccountPropertySyncPhase,
    AccountPropertySyncSegment,
    AppliedSourceValues,
    SourceSyncCheckpoint,
    _iter_parquet_row_batches,
    _list_snapshot_files,
    _mark_completed_and_maybe_cleanup,
    _matching_account_ids,
    _merge_snapshot_files,
    _read_snapshot_hashes,
    _source_values,
    _value_hash,
    _write_snapshot_hashes,
    complete_account_property_sync_segment,
    get_account_property_sync_source_ids,
    run_account_property_segment_sync,
    run_account_property_source_sync,
)
from products.customer_analytics.backend.models import CustomPropertySource, CustomPropertySyncRun
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin
from products.customer_analytics.backend.test.factories import create_account, create_custom_property_definition
from products.warehouse_sources.backend.facade.hooks import WarehouseBinding, saved_query_binding
from products.warehouse_sources.backend.facade.temporal import (
    account_property_completion_prefix,
    account_property_job_staged_prefix,
    account_property_snapshot_prefix,
)

if TYPE_CHECKING:
    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery as SavedQueryModel

_MODULE = "products.customer_analytics.backend.logic.account_property_sync"
DataWarehouseSavedQuery = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
_ACCOUNT_IDS = {
    "acct-1": UUID("00000000-0000-4000-8000-0000000000a1"),
    "acct-2": UUID("00000000-0000-4000-8000-0000000000a2"),
}
_EMPTY_COUNTS = {"rows_read": 0, "changed": 0, "matched": 0, "written": 0, "source_errors": 0, "source_count": 0}


class _WorkerStopped(Exception):
    pass


@frozen
class _RunState:
    status: str
    phase: str
    rows_read: int
    produced: int


_STAGING = _RunState(status="running", phase="staging", rows_read=0, produced=0)
_COMPLETED_ONE_ROW = _RunState(status="completed", phase="completed", rows_read=1, produced=1)
_COMPLETED_NO_ROWS = _RunState(status="completed", phase="completed", rows_read=0, produced=0)


@frozen
class _ViewWithTwoSources:
    binding: WarehouseBinding
    plan_source: CustomPropertySource
    tier_source: CustomPropertySource


def _match_known_accounts(
    team_id: int, segment: AccountPropertySyncSegment, external_ids: list[str]
) -> dict[str, UUID]:
    return {external_id: _ACCOUNT_IDS[external_id] for external_id in external_ids if external_id in _ACCOUNT_IDS}


def _apply_all_values(
    team_id: int,
    source: CustomPropertySource,
    account_ids: dict[str, UUID],
    changed: dict[str, Any],
    segment: AccountPropertySyncSegment,
) -> AppliedSourceValues:
    hashes = {external_id: _value_hash(changed[external_id]) for external_id in account_ids}
    return AppliedSourceValues(written=len(hashes), hashes=hashes, failed=False)


class AccountPropertySegmentTest(TeamScopedTestMixin, BaseTest):
    def _create_source(
        self,
        *,
        saved_query: "SavedQueryModel | None" = None,
        team: Team | None = None,
        name: str = "Plan",
        column: str = "plan",
    ) -> CustomPropertySource:
        team = team or self.team
        if saved_query is None:
            saved_query = DataWarehouseSavedQuery.objects.create(
                team=team,
                name="accounts",
                columns={"external_id": {}, "plan": {}, "tier": {}},
            )
        definition = create_custom_property_definition(team_id=team.id, name=name)
        return CustomPropertySource.objects.unscoped().create(
            team=team,
            definition=definition,
            saved_query=saved_query,
            key_column="external_id",
            source_column=column,
        )

    def _start_runs(self, source: CustomPropertySource) -> None:
        start_account_property_sync_runs(
            AccountPropertySyncRunContext(
                team_id=source.team_id,
                saved_query_id=str(source.saved_query_id),
                job_id="job-1",
            ),
            workflow_id="stage-workflow-job-1",
            workflow_run_id="00000000-0000-4000-8000-000000000001",
        )

    def _run_states(self, source: CustomPropertySource) -> dict[str, _RunState]:
        states: dict[str, _RunState] = {}
        for run in CustomPropertySyncRun.objects.for_team(source.team_id).filter(source=source, job_id="job-1"):
            assert run.segment is not None
            assert run.phase is not None
            states[run.segment] = _RunState(
                status=run.status, phase=run.phase, rows_read=run.rows_read, produced=run.produced
            )
        return states

    def _create_view_with_two_sources(self, fake: "_FakeS3", plan: str = "enterprise") -> _ViewWithTwoSources:
        plan_source = self._create_source()
        tier_source = self._create_source(saved_query=plan_source.saved_query, name="Tier", column="tier")
        self._start_runs(plan_source)
        binding = saved_query_binding(str(plan_source.saved_query_id))
        self._stage_rows(fake, binding, [{"external_id": "acct-1", "plan": plan, "tier": "gold"}])
        return _ViewWithTwoSources(binding=binding, plan_source=plan_source, tier_source=tier_source)

    def _stage_rows(self, fake: "_FakeS3", binding: WarehouseBinding, rows: list[dict[str, Any]]) -> None:
        buffer = pa.BufferOutputStream()
        pq.write_table(pa.Table.from_pylist(rows), buffer)
        path = f"{account_property_job_staged_prefix(self.team.id, binding, 'job-1')}/chunk-0.parquet"
        async_to_sync(fake._pipe_file)(path, buffer.getvalue().to_pybytes())

    def _fanout_boundaries(self, fake: "_FakeS3") -> ExitStack:
        stack = ExitStack()
        stack.enter_context(_fake_s3_patch(fake))
        stack.enter_context(patch(f"{_MODULE}.get_s3_client", return_value=fake))
        stack.enter_context(patch(f"{_MODULE}._matching_account_ids", side_effect=_match_known_accounts))
        stack.enter_context(patch(f"{_MODULE}._apply_source_values", side_effect=_apply_all_values))
        return stack

    def _run_source(
        self,
        fake: "_FakeS3",
        binding: WarehouseBinding,
        source_id: str,
        *,
        segment: AccountPropertySyncSegment = AccountPropertySyncSegment.TRACKED,
        final_attempt: bool = False,
        resume_from: SourceSyncCheckpoint | None = None,
        save_checkpoint: Callable[[SourceSyncCheckpoint], None] | None = None,
    ) -> dict[str, int]:
        with self._fanout_boundaries(fake):
            return async_to_sync(run_account_property_source_sync)(
                team_id=self.team.id,
                binding=binding,
                job_id="job-1",
                segment=segment,
                source_id=source_id,
                final_attempt=final_attempt,
                resume_from=resume_from,
                save_checkpoint=save_checkpoint,
            )

    def _complete_segment(
        self, fake: "_FakeS3", binding: WarehouseBinding, segment: AccountPropertySyncSegment
    ) -> None:
        with self._fanout_boundaries(fake):
            async_to_sync(complete_account_property_sync_segment)(
                team_id=self.team.id, binding=binding, job_id="job-1", segment=segment
            )

    def _snapshot(self, fake: "_FakeS3", binding: WarehouseBinding, source: CustomPropertySource) -> dict[str, str]:
        with _fake_s3_patch(fake):
            return async_to_sync(_read_snapshot_hashes)(
                self.team.id, binding, str(source.id), AccountPropertySyncSegment.TRACKED
            )

    def _completion_markers(self, fake: "_FakeS3", binding: WarehouseBinding) -> set[str]:
        prefix = f"{account_property_completion_prefix(self.team.id, binding, 'job-1')}/"
        return {key.removeprefix(prefix) for key in fake.store if key.startswith(prefix)}

    def _staged_files(self, fake: "_FakeS3", binding: WarehouseBinding) -> list[str]:
        prefix = account_property_job_staged_prefix(self.team.id, binding, "job-1")
        return [key for key in fake.store if key.startswith(prefix)]

    def test_source_ids_are_this_views_eligible_sources_in_a_stable_order(self) -> None:
        sources = [self._create_source()]
        view = sources[0].saved_query
        assert view is not None
        sources.append(self._create_source(saved_query=view, name="Tier", column="tier"))
        disabled = self._create_source(saved_query=view, name="Region", column="region")
        disabled.is_enabled = False
        disabled.save(update_fields=["is_enabled"])
        other_view = DataWarehouseSavedQuery.objects.create(team=self.team, name="other_accounts", columns={})
        self._create_source(saved_query=other_view, name="Seats", column="seats")
        other_team = Team.objects.create(organization=self.organization)
        self._create_source(saved_query=view, team=other_team, name="Plan", column="plan")

        source_ids = get_account_property_sync_source_ids(self.team.id, saved_query_binding(str(view.id)))

        assert source_ids == sorted(str(source.id) for source in sources)

    def test_source_sync_updates_only_its_own_source_and_segment(self) -> None:
        fake = _FakeS3()
        view = self._create_view_with_two_sources(fake)

        counts = self._run_source(fake, view.binding, str(view.plan_source.id))

        assert counts == {**_EMPTY_COUNTS, "rows_read": 1, "changed": 1, "matched": 1, "written": 1, "source_count": 1}
        assert self._run_states(view.plan_source) == {
            "tracked": _COMPLETED_ONE_ROW,
            "ignored": _STAGING,
        }
        assert self._run_states(view.tier_source) == {
            "tracked": _STAGING,
            "ignored": _STAGING,
        }
        assert self._snapshot(fake, view.binding, view.plan_source) == {"acct-1": _value_hash("enterprise")}
        assert self._snapshot(fake, view.binding, view.tier_source) == {}
        assert self._completion_markers(fake, view.binding) == {f"sources/tracked/{view.plan_source.id}.done"}
        assert len(self._staged_files(fake, view.binding)) == 1

    def test_completed_source_is_not_repeated_on_retry(self) -> None:
        fake = _FakeS3()
        view = self._create_view_with_two_sources(fake)
        first_counts = self._run_source(fake, view.binding, str(view.plan_source.id))
        self._stage_rows(fake, view.binding, [{"external_id": "acct-1", "plan": "starter", "tier": "gold"}])

        retry_counts = self._run_source(fake, view.binding, str(view.plan_source.id))

        assert first_counts["written"] == 1
        assert retry_counts == _EMPTY_COUNTS
        assert self._run_states(view.plan_source)["tracked"] == _COMPLETED_ONE_ROW
        assert self._snapshot(fake, view.binding, view.plan_source) == {"acct-1": _value_hash("enterprise")}

    @parameterized.expand(
        [
            ("same_mapping", "plan", {"acct-1": "enterprise", "acct-2": "starter"}),
            ("mapping_changed", "tier", {"acct-1": "gold", "acct-2": "silver"}),
        ]
    )
    def test_cancelled_source_sync_resumes_after_its_last_checkpoint(
        self, _case: str, resumed_column: str, expected_values: dict[str, str]
    ) -> None:
        fake = _FakeS3()
        view = self._create_view_with_two_sources(fake)
        self._stage_rows(
            fake,
            view.binding,
            [
                {"external_id": "acct-1", "plan": "enterprise", "tier": "gold"},
                {"external_id": "acct-2", "plan": "starter", "tier": "silver"},
            ],
        )
        checkpoints: list[SourceSyncCheckpoint] = []

        def cancel_after_first_checkpoint(checkpoint: SourceSyncCheckpoint) -> None:
            checkpoints.append(checkpoint)
            raise _WorkerStopped

        with (
            patch(f"{_MODULE}._PARQUET_BATCH_SIZE", 1),
            patch(f"{_MODULE}._CHECKPOINT_INTERVAL_SECONDS", 0.0),
        ):
            with pytest.raises(_WorkerStopped):
                self._run_source(
                    fake, view.binding, str(view.plan_source.id), save_checkpoint=cancel_after_first_checkpoint
                )
            view.plan_source.source_column = resumed_column
            view.plan_source.save(update_fields=["source_column"])
            heartbeat_details = [checkpoints[0].to_heartbeat_details(), {"host": "worker-1", "ts": 1.0}]
            counts = self._run_source(
                fake,
                view.binding,
                str(view.plan_source.id),
                resume_from=SourceSyncCheckpoint.from_heartbeat_details(heartbeat_details),
            )

        assert checkpoints[0].next_batch == 1
        assert counts == {**_EMPTY_COUNTS, "rows_read": 2, "changed": 2, "matched": 2, "written": 2, "source_count": 1}
        assert self._run_states(view.plan_source)["tracked"] == _RunState(
            status="completed", phase="completed", rows_read=2, produced=2
        )
        assert self._snapshot(fake, view.binding, view.plan_source) == {
            external_id: _value_hash(value) for external_id, value in expected_values.items()
        }
        assert [key for key in fake.store if "-checkpoint-" in key] == []

    @parameterized.expand(
        [
            ("other_view", AccountPropertySourceRejectedError),
            ("malformed_id", AccountPropertySourceRejectedError),
            ("other_team", None),
            ("deleted", None),
        ]
    )
    def test_source_ids_outside_this_view_are_not_processed(
        self, case: str, expected_error: type[Exception] | None
    ) -> None:
        fake = _FakeS3()
        view = self._create_view_with_two_sources(fake)
        other_view = DataWarehouseSavedQuery.objects.create(team=self.team, name="other_accounts", columns={})
        other_view_source = self._create_source(saved_query=other_view, name="Seats", column="seats")
        other_team_source = self._create_source(team=Team.objects.create(organization=self.organization))
        for source in (other_view_source, other_team_source):
            self._start_runs(source)
        source_ids = {
            "other_view": str(other_view_source.id),
            "malformed_id": "not-a-source-id",
            "other_team": str(other_team_source.id),
            "deleted": str(uuid4()),
        }

        if expected_error is None:
            assert self._run_source(fake, view.binding, source_ids[case], final_attempt=True) == _EMPTY_COUNTS
        else:
            with pytest.raises(expected_error):
                self._run_source(fake, view.binding, source_ids[case], final_attempt=True)

        running = {"tracked": _STAGING, "ignored": _STAGING}
        for source in (view.plan_source, view.tier_source, other_view_source, other_team_source):
            assert self._run_states(source) == running
        assert self._completion_markers(fake, view.binding) == set()
        assert [key for key in fake.store if "account_property_snapshot" in key] == []

    @parameterized.expand([("disabled", "is_enabled", False), ("column_removed", "source_column", None)])
    def test_ineligible_source_finishes_only_its_own_run_without_changes(
        self, _case: str, field: str, value: object
    ) -> None:
        fake = _FakeS3()
        view = self._create_view_with_two_sources(fake)
        setattr(view.plan_source, field, value)
        view.plan_source.save(update_fields=[field])

        counts = self._run_source(fake, view.binding, str(view.plan_source.id))

        assert counts == _EMPTY_COUNTS
        assert self._run_states(view.plan_source) == {
            "tracked": _COMPLETED_NO_ROWS,
            "ignored": _STAGING,
        }
        assert self._run_states(view.tier_source)["tracked"] == _STAGING
        assert self._snapshot(fake, view.binding, view.plan_source) == {}

    @parameterized.expand([("retryable", False, "running"), ("final_attempt", True, "failed")])
    def test_source_failure_keeps_completed_siblings_and_staged_rows(
        self, _case: str, final_attempt: bool, expected_status: str
    ) -> None:
        fake = _FakeS3()
        view = self._create_view_with_two_sources(fake)
        pending_source = self._create_source(saved_query=view.plan_source.saved_query, name="Seats", column="seats")
        self._start_runs(pending_source)
        self._run_source(fake, view.binding, str(view.tier_source.id))

        with (
            patch(f"{_MODULE}._iter_parquet_row_batches", side_effect=OSError("S3 unavailable")),
            pytest.raises(OSError, match="S3 unavailable"),
        ):
            self._run_source(fake, view.binding, str(view.plan_source.id), final_attempt=final_attempt)

        assert self._run_states(view.plan_source)["tracked"].status == expected_status
        assert self._run_states(view.plan_source)["ignored"].status == "running"
        assert self._run_states(view.tier_source)["tracked"] == _COMPLETED_ONE_ROW
        assert self._run_states(pending_source)["tracked"] == _STAGING
        assert self._completion_markers(fake, view.binding) == {f"sources/tracked/{view.tier_source.id}.done"}
        assert len(self._staged_files(fake, view.binding)) == 1

    @parameterized.expand([("disabled", "is_enabled", False), ("column_removed", "source_column", None)])
    def test_segment_completion_closes_leftover_runs_and_cleans_up_after_both_segments(
        self, _case: str, field: str, value: object
    ) -> None:
        fake = _FakeS3()
        view = self._create_view_with_two_sources(fake)
        setattr(view.tier_source, field, value)
        view.tier_source.save(update_fields=[field])
        for segment in AccountPropertySyncSegment:
            self._run_source(fake, view.binding, str(view.plan_source.id), segment=segment)

        self._complete_segment(fake, view.binding, AccountPropertySyncSegment.TRACKED)

        assert "tracked.done" in self._completion_markers(fake, view.binding)
        assert len(self._staged_files(fake, view.binding)) == 1

        self._complete_segment(fake, view.binding, AccountPropertySyncSegment.IGNORED)

        assert self._run_states(view.plan_source) == {"tracked": _COMPLETED_ONE_ROW, "ignored": _COMPLETED_ONE_ROW}
        assert self._run_states(view.tier_source) == {"tracked": _COMPLETED_NO_ROWS, "ignored": _COMPLETED_NO_ROWS}
        assert self._staged_files(fake, view.binding) == []

    @parameterized.expand([("not_dispatched",), ("retryable_failure",), ("final_attempt",), ("missing_run",)])
    def test_segment_completion_refuses_a_segment_with_an_incomplete_source(self, case: str) -> None:
        fake = _FakeS3()
        view = self._create_view_with_two_sources(fake)
        for source in (view.plan_source, view.tier_source):
            self._run_source(fake, view.binding, str(source.id), segment=AccountPropertySyncSegment.IGNORED)
        self._complete_segment(fake, view.binding, AccountPropertySyncSegment.IGNORED)
        self._run_source(fake, view.binding, str(view.tier_source.id))
        if case in {"retryable_failure", "final_attempt"}:
            with (
                patch(f"{_MODULE}._iter_parquet_row_batches", side_effect=OSError("S3 unavailable")),
                pytest.raises(OSError),
            ):
                self._run_source(fake, view.binding, str(view.plan_source.id), final_attempt=case == "final_attempt")
        elif case == "missing_run":
            CustomPropertySyncRun.objects.for_team(self.team.id).filter(
                source=view.plan_source, job_id="job-1", segment="tracked"
            ).delete()
        source_runs_before = self._run_states(view.plan_source)

        with pytest.raises(AccountPropertySyncSegmentIncompleteError):
            self._complete_segment(fake, view.binding, AccountPropertySyncSegment.TRACKED)

        markers = self._completion_markers(fake, view.binding)
        assert "ignored.done" in markers
        assert "tracked.done" not in markers
        assert self._run_states(view.plan_source) == source_runs_before
        assert self._run_states(view.tier_source)["tracked"] == _COMPLETED_ONE_ROW
        assert len(self._staged_files(fake, view.binding)) == 1

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

        async def batches(*args: object, **_kwargs: object) -> AsyncIterator[list[dict[str, Any]]]:
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

        async def no_batches(*args: object, **_kwargs: object) -> AsyncIterator[list[dict[str, Any]]]:
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

        async def no_batches(*args: object, **_kwargs: object) -> AsyncIterator[list[dict[str, Any]]]:
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


_CHECKPOINT_DETAILS = {
    "next_batch": 3,
    "rows_read": 3,
    "changed": 1,
    "matched": 1,
    "written": 1,
    "failed": False,
    "key_column": "external_id",
    "source_column": "plan",
}


@pytest.mark.parametrize(
    "details",
    [
        [],
        [{"host": "worker-1", "ts": 1.0}],
        [{**_CHECKPOINT_DETAILS, "next_batch": -1}],
        [{**_CHECKPOINT_DETAILS, "failed": "no"}],
    ],
)
def test_unusable_heartbeat_details_restart_the_source_sync(details: list[object]) -> None:
    assert SourceSyncCheckpoint.from_heartbeat_details(details) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("source_columns", [("value_0", "value_1"), ("value_0", None), ()])
async def test_each_staged_batch_is_shared_across_sources(source_columns: tuple[str | None, ...]) -> None:
    binding = saved_query_binding("019f0000-0000-7000-8000-000000000001")
    sources = []
    for index, source_column in enumerate(source_columns):
        source = MagicMock()
        source.id = f"source-{index}"
        source.key_column = "organization_id"
        source.source_column = source_column
        sources.append(source)
    batch_calls = 0

    async def batches(*args: object, **_kwargs: object) -> AsyncIterator[list[dict[str, Any]]]:
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
        counts = await run_account_property_segment_sync(
            team_id=7,
            binding=binding,
            job_id="job-1",
            segment=AccountPropertySyncSegment.TRACKED,
        )

    assert batch_calls == 1
    assert counts["source_count"] == sum(column is not None for column in source_columns)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_source_values", [False, True])
async def test_sync_records_each_phase_duration(invalid_source_values: bool) -> None:
    binding = saved_query_binding("019f0000-0000-7000-8000-000000000001")
    source = MagicMock()
    source.id = "source-1"
    source.key_column = "organization_id"
    source.source_column = "value"
    phase_duration_recorder = MagicMock()

    async def batches(*args: object, **_kwargs: object) -> AsyncIterator[list[dict[str, Any]]]:
        yield [{"organization_id": "org-1", "value": 1}, {"organization_id": "org-2", "value": "invalid"}]

    with (
        patch(f"{_MODULE}._segment_already_completed", new=AsyncMock(return_value=False)),
        patch(f"{_MODULE}._enabled_sources", return_value=[source]),
        patch(f"{_MODULE}._read_snapshot_hashes", new=AsyncMock(return_value={})),
        patch(f"{_MODULE}._iter_parquet_row_batches", side_effect=batches),
        patch(f"{_MODULE}._matching_account_ids", return_value={"org-1": MagicMock(), "org-2": MagicMock()}),
        patch(
            f"{_MODULE}._apply_source_values",
            return_value=AppliedSourceValues(
                written=1 if invalid_source_values else 2,
                hashes={"org-1": "hash"} if invalid_source_values else {"org-1": "hash", "org-2": "hash-2"},
                failed=invalid_source_values,
            ),
        ),
        patch(f"{_MODULE}._write_snapshot_hashes", new=AsyncMock()),
        patch(f"{_MODULE}._mark_completed_and_maybe_cleanup", new=AsyncMock()),
        patch(f"{_MODULE}.finish_account_property_sync_runs"),
        patch(f"{_MODULE}.finalize_account_property_sync_runs"),
        patch(f"{_MODULE}.record_account_property_sync_phase_duration", phase_duration_recorder),
    ):
        if invalid_source_values:
            with pytest.raises(AccountPropertySourceValueError) as raised:
                await run_account_property_segment_sync(
                    team_id=7,
                    binding=binding,
                    job_id="job-1",
                    segment=AccountPropertySyncSegment.TRACKED,
                )
            counts = raised.value.counts
        else:
            counts = await run_account_property_segment_sync(
                team_id=7,
                binding=binding,
                job_id="job-1",
                segment=AccountPropertySyncSegment.TRACKED,
            )

    assert counts == {
        "rows_read": 2,
        "changed": 2,
        "matched": 2,
        "written": 1 if invalid_source_values else 2,
        "source_errors": int(invalid_source_values),
        "source_count": 1,
    }
    assert [call.kwargs["phase"] for call in phase_duration_recorder.call_args_list] == [
        phase.value for phase in AccountPropertySyncPhase
    ]


class _ReadTrackingFile(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.bytes_read = 0

    def read(self, size: int | None = -1, /) -> bytes:
        data = super().read(size)
        self.bytes_read += len(data)
        return data


@pytest.mark.asyncio
@pytest.mark.parametrize("columns", [None, ["organization_id", "plan"], ["organization_id", "missing"]])
async def test_staged_parquet_is_decoded_in_bounded_batches(columns: list[str] | None) -> None:
    binding = saved_query_binding("019f0000-0000-7000-8000-000000000001")
    table = pa.table(
        {
            "organization_id": [f"org-{index}" for index in range(50_001)],
            "plan": ["gold"] * 50_001,
            "unused": [hashlib.sha256(str(index).encode()).digest() for index in range(50_001)],
        }
    )
    buffer = pa.BufferOutputStream()
    pq.write_table(table, buffer)
    data = buffer.getvalue().to_pybytes()
    projected_file = _ReadTrackingFile(data)
    client = MagicMock()
    client._ls = AsyncMock(return_value=[{"Key": "prefix/chunk.parquet", "type": "file"}])
    client._cat_file = AsyncMock(return_value=data)
    client.open.return_value = projected_file

    with (
        patch(f"{_MODULE}.aget_s3_client", return_value=_S3ClientContext(client)),
        patch(f"{_MODULE}.get_s3_client", return_value=client),
    ):
        batches = [rows async for rows in _iter_parquet_row_batches(7, binding, "job-1", columns=columns)]

    assert [len(rows) for rows in batches] == [50_000, 1]
    expected_columns = set(table.column_names) if columns is None else set(columns) & set(table.column_names)
    assert [set(rows[0]) for rows in batches] == [expected_columns, expected_columns]
    if columns is not None:
        client._cat_file.assert_not_awaited()
        assert 0 < projected_file.bytes_read < len(data)


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

    def open(self, path: str, mode: str, *, cache_type: str) -> io.BytesIO:
        return io.BytesIO(self.store[aps._s3_key(path)])

    async def _pipe_file(self, path: str, data: bytes) -> None:
        self._clock += 1
        key = aps._s3_key(path)
        self.store[key] = data
        self.times[key] = self._clock

    async def _rm(self, paths: str | list[str], *, recursive: bool = False) -> None:
        for path in [paths] if isinstance(paths, str) else paths:
            key = aps._s3_key(path)
            for stored_key in [stored for stored in self.store if stored.startswith(key)] if recursive else [key]:
                self.store.pop(stored_key, None)
                self.times.pop(stored_key, None)


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
@pytest.mark.parametrize("final_hashes", [{"b": "h2", "c": "h2"}, {}])
async def test_snapshot_write_compacts_prior_files_newest_hash_winning(final_hashes: dict[str, str]) -> None:
    fake = _FakeS3()
    await _write(fake, "job-1", {"a": "h1", "b": "h1"})
    with _fake_s3_patch(fake):
        await aps._write_snapshot_delta(7, _SNAPSHOT_BINDING, "src", _SEGMENT, "job-2-checkpoint-1", {"b": "h2"})
    await _write(fake, "job-2", final_hashes)

    assert len(fake.store) == 1
    assert await _read(fake) == {"a": "h1", "b": "h2", **final_hashes}


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
