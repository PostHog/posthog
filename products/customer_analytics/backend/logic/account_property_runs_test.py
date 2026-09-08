from datetime import timedelta

from posthog.test.base import BaseTest

from django.apps import apps
from django.utils import timezone

from products.customer_analytics.backend.facade import api
from products.customer_analytics.backend.logic.account_property_runs import (
    AccountPropertySyncRunContext,
    AccountPropertySyncRunOutcome,
    finalize_account_property_sync_runs,
    finish_account_property_sync_runs,
    start_account_property_sync_runs,
    update_account_property_sync_runs_phase,
)
from products.customer_analytics.backend.models import CustomPropertySource, CustomPropertySyncRun
from products.customer_analytics.backend.models.custom_property_sync_run import SyncPhase, SyncSegment, SyncStatus
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin
from products.customer_analytics.backend.test.factories import create_custom_property_definition

DataWarehouseSavedQuery = apps.get_model("data_modeling", "DataWarehouseSavedQuery")


class TestAccountPropertyRuns(TeamScopedTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="accounts",
            columns={"external_id": {}, "plan": {}},
        )
        definition = create_custom_property_definition(team_id=self.team.id, name="Plan")
        self.source = CustomPropertySource.objects.create(
            team=self.team,
            definition=definition,
            saved_query=self.saved_query,
            key_column="external_id",
            source_column="plan",
        )
        self.context = AccountPropertySyncRunContext(
            team_id=self.team.id,
            saved_query_id=str(self.saved_query.id),
            job_id="job-1",
        )

    def _create_outcome(
        self,
        *,
        rows_read: int = 10,
        changed: int = 4,
        matched: int = 3,
        written: int = 2,
        error: str | None = None,
    ) -> AccountPropertySyncRunOutcome:
        return AccountPropertySyncRunOutcome(
            source_id=self.source.id,
            rows_read=rows_read,
            changed=changed,
            matched=matched,
            written=written,
            error=error,
        )

    def _start_runs(
        self,
        workflow_id: str = "stage-workflow-job-1",
        workflow_run_id: str = "00000000-0000-4000-8000-000000000001",
    ) -> None:
        start_account_property_sync_runs(
            self.context,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
        )

    def test_start_opens_both_segments_before_staging_and_exposes_them_through_the_api(self) -> None:
        self._start_runs()

        runs = CustomPropertySyncRun.objects.for_team(self.team.id).filter(source=self.source)
        assert runs.count() == 2
        assert {run.segment for run in runs} == {"tracked", "ignored"}
        assert {run.phase for run in runs} == {"staging"}
        assert {run.workflow_id for run in runs} == {"stage-workflow-job-1"}
        assert {str(run.workflow_run_id) for run in runs} == {"00000000-0000-4000-8000-000000000001"}
        assert {run.attempt for run in runs} == {0}

        views, total_count = api.list_custom_property_sync_runs(
            self.team.id,
            str(self.source.id),
            offset=0,
            limit=10,
        )
        assert total_count == 2
        assert {view.account_segment for view in views} == {"tracked", "ignored"}
        assert {view.sync_phase for view in views} == {"staging"}
        assert {view.job_id for view in views} == {"job-1"}
        assert {view.workflow_id for view in views} == {None}
        assert {view.workflow_run_id for view in views} == {None}
        assert {view.temporal_url for view in views} == {None}

        staff_views, _ = api.list_custom_property_sync_runs(
            self.team.id,
            str(self.source.id),
            offset=0,
            limit=10,
            include_temporal_urls=True,
        )
        assert {view.workflow_id for view in staff_views} == {"stage-workflow-job-1"}
        assert {str(view.workflow_run_id) for view in staff_views} == {"00000000-0000-4000-8000-000000000001"}
        assert all(view.temporal_url is not None for view in staff_views)

        search_views, search_count = api.list_custom_property_sync_runs(
            self.team.id,
            str(self.source.id),
            offset=0,
            limit=20,
            search="ignored",
        )
        assert search_count == 1
        assert [view.account_segment for view in search_views] == ["ignored"]

    def test_phase_updates_record_retries_without_regressing_the_sibling(self) -> None:
        self._start_runs()
        update_account_property_sync_runs_phase(
            self.context,
            phase=SyncPhase.DISPATCHING,
            workflow_id="stage-workflow-job-1",
            workflow_run_id="00000000-0000-4000-8000-000000000001",
            attempt=2,
        )
        update_account_property_sync_runs_phase(
            self.context,
            phase=SyncPhase.SYNCING,
            workflow_id="sync-workflow-job-1-tracked",
            workflow_run_id="00000000-0000-4000-8000-000000000002",
            attempt=3,
            segment=SyncSegment.TRACKED,
        )
        update_account_property_sync_runs_phase(
            self.context,
            phase=SyncPhase.DISPATCHING,
            workflow_id="stage-workflow-job-1",
            workflow_run_id="00000000-0000-4000-8000-000000000001",
            attempt=4,
        )

        tracked = CustomPropertySyncRun.objects.for_team(self.team.id).get(source=self.source, segment="tracked")
        ignored = CustomPropertySyncRun.objects.for_team(self.team.id).get(source=self.source, segment="ignored")
        assert (tracked.phase, tracked.attempt, tracked.workflow_id, str(tracked.workflow_run_id)) == (
            "syncing",
            3,
            "sync-workflow-job-1-tracked",
            "00000000-0000-4000-8000-000000000002",
        )
        assert (ignored.phase, ignored.attempt, ignored.workflow_id, str(ignored.workflow_run_id)) == (
            "dispatching",
            4,
            "stage-workflow-job-1",
            "00000000-0000-4000-8000-000000000001",
        )

    def test_account_runs_remain_active_during_their_workflow_timeout(self) -> None:
        self._start_runs()
        CustomPropertySyncRun.objects.for_team(self.team.id).filter(source=self.source).update(
            started_at=timezone.now() - timedelta(hours=7)
        )

        views, _ = api.list_custom_property_sync_runs(
            self.team.id,
            str(self.source.id),
            offset=0,
            limit=10,
        )

        assert {view.status for view in views} == {"running"}

    def test_staging_failure_finishes_both_segments_with_a_safe_error(self) -> None:
        self._start_runs()

        finalize_account_property_sync_runs(
            self.context,
            status=SyncStatus.FAILED,
            phase=SyncPhase.STAGING,
            error="Couldn't prepare warehouse rows.",
        )

        runs = CustomPropertySyncRun.objects.for_team(self.team.id).filter(source=self.source)
        assert {run.status for run in runs} == {"failed"}
        assert {run.phase for run in runs} == {"staging"}
        assert {run.error for run in runs} == {"Couldn't prepare warehouse rows."}
        assert all(run.finished_at is not None for run in runs)
        self.source.refresh_from_db()
        assert self.source.last_sync_error == "Couldn't prepare warehouse rows."
        assert self.source.consecutive_failures == 1

        finalize_account_property_sync_runs(
            self.context,
            status=SyncStatus.FAILED,
            phase=SyncPhase.STAGING,
            error="Couldn't prepare warehouse rows.",
        )
        self.source.refresh_from_db()
        assert self.source.consecutive_failures == 1

    def test_finishing_both_segments_updates_the_source_summary(self) -> None:
        self.source.last_sync_error = "Previous failure"
        self.source.consecutive_failures = 2
        self.source.save(update_fields=["last_sync_error", "consecutive_failures"])
        self._start_runs()
        tracked_finished_at = timezone.now()
        ignored_finished_at = tracked_finished_at + timedelta(seconds=2)

        finish_account_property_sync_runs(
            self.context,
            SyncSegment.TRACKED,
            [self._create_outcome(written=3)],
            finished_at=tracked_finished_at,
        )
        source_after_tracked = CustomPropertySource.objects.for_team(self.team.id).get(id=self.source.id)
        assert source_after_tracked.last_synced_at is None
        assert source_after_tracked.last_sync_error == "Previous failure"
        assert source_after_tracked.consecutive_failures == 2

        finish_account_property_sync_runs(
            self.context,
            SyncSegment.IGNORED,
            [self._create_outcome(written=0)],
            finished_at=ignored_finished_at,
        )
        source_after_ignored = CustomPropertySource.objects.for_team(self.team.id).get(id=self.source.id)
        assert source_after_ignored.last_synced_at == ignored_finished_at
        assert source_after_ignored.last_sync_error is None
        assert source_after_ignored.consecutive_failures == 0

    def test_retry_reuses_rows_and_preserves_a_completed_segment(self) -> None:
        self._start_runs()
        finalize_account_property_sync_runs(
            self.context,
            status=SyncStatus.FAILED,
            phase=SyncPhase.DISPATCHING,
            error="Couldn't start account updates.",
        )
        self._start_runs("stage-workflow-job-1-retry")
        finish_account_property_sync_runs(self.context, SyncSegment.TRACKED, [self._create_outcome(written=3)])
        self._start_runs("stage-workflow-job-1-retry-2")

        tracked = CustomPropertySyncRun.objects.for_team(self.team.id).get(source=self.source, segment="tracked")
        ignored = CustomPropertySyncRun.objects.for_team(self.team.id).get(source=self.source, segment="ignored")
        assert (tracked.status, tracked.phase, tracked.produced) == ("completed", "completed", 3)
        assert (ignored.status, ignored.phase, ignored.error) == ("running", "staging", None)
        assert CustomPropertySyncRun.objects.for_team(self.team.id).filter(source=self.source).count() == 2
