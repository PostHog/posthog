from datetime import UTC, datetime
from uuid import uuid4

from posthog.test.base import APIBaseTest

from products.customer_analytics.backend.logic.person_property_runs import (
    MAX_CONSECUTIVE_SYNC_FAILURES,
    record_sync_run,
)
from products.customer_analytics.backend.models import CustomPropertySource, CustomPropertySyncRun, TargetType
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin
from products.customer_analytics.backend.test.factories import create_custom_property_definition
from products.warehouse_sources.backend.facade.hooks import PersonPropertySyncRunRecord
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


class TestRecordSyncRun(TeamScopedTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        definition = create_custom_property_definition(
            team_id=self.team.id, name="Plan tier", target_type=TargetType.PERSON.value
        )
        source = ExternalDataSource.objects.create(
            team=self.team, source_id="s", connection_id="c", status="Running", source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(team=self.team, source=source, name="users")
        self.source = CustomPropertySource.objects.create(
            team=self.team,
            definition=definition,
            key_column="distinct_id",
            external_data_schema=schema,
            column_property_map={"plan": "plan_tier"},
            is_enabled=True,
        )
        self.schema_id = str(schema.id)

    def _record(self, **overrides) -> PersonPropertySyncRunRecord:
        kwargs: dict = {
            "team_id": self.team.id,
            "schema_id": self.schema_id,
            "source_id": str(self.source.id),
            "job_id": "job-1",
            "trigger": "scheduled",
            "status": "completed",
            "started_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
            "finished_at": datetime(2026, 1, 1, 0, 1, tzinfo=UTC).isoformat(),
            "rows_read": 10,
            "changed": 4,
            "existing": 3,
            "produced": 3,
            "skipped_missing_person": 1,
            "error": None,
        }
        kwargs.update(overrides)
        return PersonPropertySyncRunRecord(**kwargs)

    def test_completed_run_persists_counts_and_clears_source_status(self):
        # Regression: the person path never persisted a run or updated status; a silent no-op would
        # leave the UI (and sourceSyncStatus) blank after a real sync.
        record_sync_run(self._record())

        run = CustomPropertySyncRun.objects.unscoped().get(source_id=self.source.id)
        assert run.status == "completed"
        assert (run.rows_read, run.changed, run.existing, run.produced, run.skipped_missing_person) == (10, 4, 3, 3, 1)
        assert run.trigger == "scheduled"

        self.source.refresh_from_db()
        assert self.source.last_synced_at is not None
        assert self.source.last_sync_error is None
        assert self.source.consecutive_failures == 0

    def test_failed_run_increments_failures_and_records_error(self):
        self.source.consecutive_failures = 2
        self.source.save()

        record_sync_run(self._record(status="failed", error="boom"))

        run = CustomPropertySyncRun.objects.unscoped().get(source_id=self.source.id)
        assert run.status == "failed" and run.error == "boom"
        self.source.refresh_from_db()
        assert self.source.consecutive_failures == 3
        assert self.source.last_sync_error == "boom"
        assert self.source.is_enabled is True

    def test_auto_disables_at_failure_cap(self):
        # Regression: a source failing forever should stop syncing, matching the account path's cap.
        self.source.consecutive_failures = MAX_CONSECUTIVE_SYNC_FAILURES - 1
        self.source.save()

        record_sync_run(self._record(status="failed", error="boom"))

        self.source.refresh_from_db()
        assert self.source.is_enabled is False

    def test_unknown_source_is_a_noop(self):
        # A run for a since-deleted source must not crash or orphan a row.
        record_sync_run(self._record(source_id=str(uuid4())))
        assert not CustomPropertySyncRun.objects.unscoped().filter(job_id="job-1").exists()

    def test_backfill_reconciles_running_placeholder_in_place(self):
        # The UI/auto path pre-creates a 'running' row; a backfill terminal record must update it in
        # place (one row, not a running + completed pair) so the progress row resolves.
        placeholder = CustomPropertySyncRun.objects.create(
            team_id=self.team.id, source=self.source, schema_id=self.schema_id, trigger="backfill", status="running"
        )
        record_sync_run(self._record(trigger="backfill", status="completed", produced=5))

        runs = CustomPropertySyncRun.objects.unscoped().filter(source=self.source)
        assert runs.count() == 1
        run = runs.get()
        assert run.id == placeholder.id
        assert run.status == "completed" and run.produced == 5

    def test_scheduled_run_leaves_a_running_placeholder_untouched(self):
        # A scheduled sync must not hijack a backfill's running placeholder; it always inserts its own.
        placeholder = CustomPropertySyncRun.objects.create(
            team_id=self.team.id, source=self.source, schema_id=self.schema_id, trigger="backfill", status="running"
        )
        record_sync_run(self._record(trigger="scheduled", status="completed"))

        assert CustomPropertySyncRun.objects.unscoped().filter(source=self.source).count() == 2
        placeholder.refresh_from_db()
        assert placeholder.status == "running"

    def test_scheduled_retry_dedups_on_job_id_and_counts_failure_once(self):
        # The scheduled sync activity retries up to 3 times, calling the recorder on each failed
        # attempt. Dedup on job_id so retries update the one row instead of inserting a fresh failed
        # row and re-incrementing the failure streak (which would auto-disable from retry noise).
        record_sync_run(self._record(status="failed", error="boom"))
        record_sync_run(self._record(status="failed", error="boom"))
        record_sync_run(self._record(status="failed", error="boom"))

        runs = CustomPropertySyncRun.objects.unscoped().filter(source=self.source, job_id="job-1")
        assert runs.count() == 1
        self.source.refresh_from_db()
        assert self.source.consecutive_failures == 1

    def test_scheduled_retry_that_finally_succeeds_clears_the_failure(self):
        # A transient failure followed by a successful retry (same job_id) must resolve the row to
        # completed and reset the source's failure streak / last-synced time.
        record_sync_run(self._record(status="failed", error="boom"))
        record_sync_run(self._record(status="completed", error=None))

        runs = CustomPropertySyncRun.objects.unscoped().filter(source=self.source, job_id="job-1")
        assert runs.count() == 1
        assert runs.get().status == "completed"
        self.source.refresh_from_db()
        assert self.source.consecutive_failures == 0
        assert self.source.last_synced_at is not None
        assert self.source.last_sync_error is None
