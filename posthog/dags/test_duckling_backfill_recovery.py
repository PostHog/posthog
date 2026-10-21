from datetime import timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from dagster import (
    DagsterInstance,
    DagsterRun,
    DagsterRunStatus,
    Permissive,
    SensorResult,
    build_sensor_context,
    job,
    op,
)
from dagster._core.remote_origin import RegisteredCodeLocationOrigin, RemoteJobOrigin, RemoteRepositoryOrigin
from parameterized import parameterized

from posthog.dags.duckling_backfill_recovery import (
    MAX_INFLIGHT_RECOVERIES,
    RECOVERY_TAG,
    RETRY_ATTEMPT_TAG,
    duckling_backfill_recovery_sensor,
)

from products.data_warehouse.backend.facade.backfill_status import (
    BackfillOutcome,
    record_backfill_finished,
    record_backfill_outcome,
    record_backfill_recovery,
    record_backfill_started,
)
from products.data_warehouse.backend.models import ManagedWarehouseBackfillPartition


@op(name="duckling_events_backfill", config_schema=Permissive())
def events_op() -> None:
    pass


@job(name="duckling_events_backfill_job")
def events_job() -> None:
    events_op()


@op(name="duckling_persons_backfill", config_schema=Permissive())
def persons_op() -> None:
    pass


@job(name="duckling_persons_backfill_job")
def persons_job() -> None:
    persons_op()


@time_machine.travel("2026-07-13", tick=False)
class TestBackfillRecovery(BaseTest):
    def _failed(
        self,
        instance: DagsterInstance,
        *,
        dataset: str = "events",
        period: str = "2026-04",
        attempt: int = 0,
        config: dict[str, object] | None = None,
    ) -> DagsterRun:
        partition = f"{self.team.pk}_{period}" if period else str(self.team.pk)
        instance.add_dynamic_partitions(f"duckling_{dataset}_backfill", [partition])
        run = instance.create_run_for_job(
            events_job if dataset == "events" else persons_job,
            status=DagsterRunStatus.STARTED,
            tags={"dagster/partition": partition, RETRY_ATTEMPT_TAG: str(attempt)},
            run_config=config,
        )
        instance.report_run_failed(run)
        return run

    def _evaluate(self, instance: DagsterInstance, *, enabled: bool = True, cursor: str | None = None) -> SensorResult:
        with (
            build_sensor_context(instance=instance, cursor=cursor) as context,
            patch(
                "posthog.dags.duckling_backfill_recovery.list_enabled_backfill_team_memberships",
                return_value=[MagicMock(team_id=self.team.pk)] if enabled else [],
            ),
        ):
            result = duckling_backfill_recovery_sensor(context)
            assert isinstance(result, SensorResult)
            return result

    @parameterized.expand(
        [("month", "events", "2026-04"), ("old_day", "events", "2026-06-01"), ("persons", "persons", "")]
    )
    def test_recovers_failed_history_and_old_daily_runs(self, _name: str, dataset: str, period: str) -> None:
        with DagsterInstance.ephemeral() as instance:
            failed = self._failed(instance, dataset=dataset, period=period)
            initial = self._evaluate(instance)
            assert initial.run_requests == []
            row = ManagedWarehouseBackfillPartition.objects.for_team(self.team.pk).get(dataset=dataset)
            assert row.retry_at is not None
            deadline = row.retry_at
            with time_machine.travel(deadline + timedelta(seconds=1), tick=False):
                result = self._evaluate(instance)
                repeated = self._evaluate(instance)

            assert result.run_requests is not None and len(result.run_requests) == 1
            assert repeated.run_requests is not None
            request = result.run_requests[0]
            assert request.run_key == repeated.run_requests[0].run_key == f"recover:{failed.run_id}"
            assert request.tags[RETRY_ATTEMPT_TAG] == "1"
            assert request.job_name == failed.job_name

    @parameterized.expand(
        [
            ("budget", 3, {}),
            ("destructive", 0, {"delete_tables": True}),
            ("append_only", 0, {"cleanup_existing_partition_data": False}),
        ]
    )
    def test_stops_recovery_and_projects_intervention(
        self, _name: str, attempt: int, config: dict[str, object]
    ) -> None:
        with DagsterInstance.ephemeral() as instance:
            self._failed(instance, attempt=attempt, config={"ops": {"duckling_events_backfill": {"config": config}}})
            with time_machine.travel("2026-07-14", tick=False):
                result = self._evaluate(instance)

            assert result.run_requests == []
            row = ManagedWarehouseBackfillPartition.objects.for_team(self.team.pk).get(dataset="events")
            assert row.retry_exhausted
            assert row.retry_at is None

    @parameterized.expand(
        [
            ("success", DagsterRunStatus.SUCCESS),
            ("queued", DagsterRunStatus.QUEUED),
            ("canceled", DagsterRunStatus.CANCELED),
        ]
    )
    def test_does_not_retry_superseded_failures(self, _name: str, status: DagsterRunStatus) -> None:
        with DagsterInstance.ephemeral() as instance:
            failed = self._failed(instance)
            instance.create_run_for_job(
                events_job,
                status=status,
                tags={"dagster/partition": failed.tags["dagster/partition"]},
                remote_job_origin=RemoteJobOrigin(
                    RemoteRepositoryOrigin(RegisteredCodeLocationOrigin("data-stack"), "repository"), events_job.name
                ),
            )
            with time_machine.travel("2026-07-14", tick=False):
                assert self._evaluate(instance).run_requests == []

    def test_disabled_warehouse_is_not_retried(self) -> None:
        with DagsterInstance.ephemeral() as instance:
            self._failed(instance)
            with time_machine.travel("2026-07-14", tick=False):
                assert self._evaluate(instance, enabled=False).run_requests == []

    def test_retry_queue_is_bounded(self) -> None:
        with DagsterInstance.ephemeral() as instance:
            self._failed(instance)
            for _ in range(MAX_INFLIGHT_RECOVERIES):
                instance.create_run_for_job(
                    events_job,
                    status=DagsterRunStatus.QUEUED,
                    tags={RECOVERY_TAG: "true"},
                    remote_job_origin=RemoteJobOrigin(
                        RemoteRepositoryOrigin(RegisteredCodeLocationOrigin("data-stack"), "repository"),
                        events_job.name,
                    ),
                )
            with time_machine.travel("2026-07-14", tick=False):
                assert self._evaluate(instance).run_requests == []

    @parameterized.expand(
        [
            ("month_day", "events", "2026-04", "2026-04-03"),
            ("day_month", "events", "2026-04-03", "2026-04"),
            ("full_day", "persons", "", "2026-04-03"),
            ("day_full", "persons", "2026-04-03", ""),
        ]
    )
    def test_does_not_overlap_an_active_partition(self, _name: str, dataset: str, period: str, active: str) -> None:
        with DagsterInstance.ephemeral() as instance:
            self._failed(instance, dataset=dataset, period=period)
            active_partition = f"{self.team.pk}_{active}" if active else str(self.team.pk)
            instance.create_run_for_job(
                events_job if dataset == "events" else persons_job,
                status=DagsterRunStatus.STARTED,
                tags={"dagster/partition": active_partition},
            )
            with time_machine.travel("2026-07-14", tick=False):
                assert self._evaluate(instance).run_requests == []

    def test_older_attempt_cannot_finish_or_reschedule_a_newer_attempt(self) -> None:
        partition = f"{self.team.pk}_2026-04"
        record_backfill_started(team_id=self.team.pk, dataset="events", partition_key=partition, run_id="old")
        record_backfill_started(team_id=self.team.pk, dataset="events", partition_key=partition, run_id="new")
        record_backfill_finished(
            team_id=self.team.pk, dataset="events", partition_key=partition, run_id="old", error=RuntimeError()
        )
        record_backfill_recovery(
            team_id=self.team.pk, dataset="events", partition_key=partition, run_id="old", retry_at=None, exhausted=True
        )
        record_backfill_outcome(
            team_id=self.team.pk,
            dataset="events",
            partition_key=partition,
            run_id="old",
            outcome=BackfillOutcome.SUCCEEDED,
        )

        row = ManagedWarehouseBackfillPartition.objects.for_team(self.team.pk).get(dataset="events")
        assert row.run_id == "new"
        assert row.lifecycle_state == ManagedWarehouseBackfillPartition.LifecycleState.RUNNING
        assert row.completed_at is None

    def test_failures_before_step_start_preserve_the_retry_budget_and_status(self) -> None:
        with DagsterInstance.ephemeral() as instance:
            latest = self._failed(instance)
            self._evaluate(instance)
            row = ManagedWarehouseBackfillPartition.objects.for_team(self.team.pk).get(dataset="events")
            for attempt in range(1, 4):
                assert row.retry_at is not None
                with time_machine.travel(row.retry_at + timedelta(seconds=1), tick=False):
                    result = self._evaluate(instance)
                    assert result.run_requests is not None and len(result.run_requests) == 1
                    request = result.run_requests[0]
                    assert request.tags[RETRY_ATTEMPT_TAG] == str(attempt)
                    latest = instance.create_run_for_job(
                        events_job,
                        status=DagsterRunStatus.FAILURE,
                        tags={**request.tags, "dagster/partition": latest.tags["dagster/partition"]},
                    )
                    self._evaluate(instance)
                row.refresh_from_db()
                assert row.run_id == latest.run_id

            assert row.retry_exhausted
            assert row.retry_at is None

    def test_scan_cursor_reaches_older_failed_partitions(self) -> None:
        with DagsterInstance.ephemeral() as instance:
            first = self._failed(instance, period="2026-03")
            second = self._failed(instance, period="2026-04")
            with (
                time_machine.travel("2026-07-14", tick=False),
                patch("posthog.dags.duckling_backfill_recovery.SCAN_LIMIT", 1),
            ):
                result = self._evaluate(instance)
                following = self._evaluate(instance, cursor=result.cursor)
            assert result.run_requests and following.run_requests
            assert {result.run_requests[0].partition_key, following.run_requests[0].partition_key} == {
                first.tags["dagster/partition"],
                second.tags["dagster/partition"],
            }
