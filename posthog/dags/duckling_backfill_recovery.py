import json
import random
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from django.utils import timezone

from dagster import (
    DagsterRunStatus,
    DefaultSensorStatus,
    RunRecord,
    RunRequest,
    RunsFilter,
    SensorEvaluationContext,
    SensorResult,
    sensor,
)

from posthog.dags.events_backfill_to_duckling import (
    EVENTS_BACKFILL_TARGET_QUEUE_DEPTH,
    _repair_stale_running_statuses,
    duckling_events_backfill_job,
    duckling_persons_backfill_job,
    parse_partition_key_dates,
)

from products.data_warehouse.backend.facade.backfill_status import record_backfill_recovery
from products.managed_warehouse.backend.facade.team_state import list_enabled_backfill_team_memberships

RETRY_ATTEMPT_TAG = "duckling/retry_attempt"
RETRY_OF_TAG = "duckling/retry_of"
RECOVERY_TAG = "duckling/recovery"
RETRY_DELAYS = (60, 300, 900)
SCAN_LIMIT = 50
MAX_INFLIGHT_RECOVERIES = 10
INFLIGHT_STATUSES = [
    DagsterRunStatus.QUEUED,
    DagsterRunStatus.NOT_STARTED,
    DagsterRunStatus.STARTING,
    DagsterRunStatus.STARTED,
    DagsterRunStatus.CANCELING,
]


class BackfillRecovery:
    def __init__(self, context: SensorEvaluationContext, dataset: str, enabled_teams: set[int]) -> None:
        self.context = context
        self.dataset = dataset
        self.enabled_teams = enabled_teams
        self.job_name = f"duckling_{dataset}_backfill_job"
        self.asset_name = f"duckling_{dataset}_backfill"
        self.partitions = set(context.instance.get_dynamic_partitions(f"duckling_{dataset}_backfill"))

    def _is_safe_to_replay(self, record: RunRecord) -> bool:
        ops = record.dagster_run.run_config.get("ops", {})
        if not isinstance(ops, Mapping):
            return False
        asset_config = ops.get(self.asset_name, {})
        if not isinstance(asset_config, Mapping):
            return False
        config = asset_config.get("config", {})
        if not isinstance(config, Mapping):
            return False
        return not any(
            config.get(key, False) for key in ("delete_tables", "dry_run", "skip_ducklake_registration")
        ) and (config.get("cleanup_existing_partition_data", True) is True)

    def _eligible_team(self, partition: str) -> int | None:
        if partition not in self.partitions:
            return None
        try:
            team_id = int(partition.split("_", 1)[0])
            if self.dataset == "events" or "_" in partition:
                _, dates = parse_partition_key_dates(partition)
                today = timezone.now().date()
                if not dates or dates[-1].date() >= today:
                    return None
                if len(partition.split("_", 1)[1]) == 7 and dates[0].date() >= today.replace(day=1):
                    return None
        except ValueError:
            return None
        return team_id if team_id in self.enabled_teams else None

    def _request(self, record: RunRecord, active_partitions: set[str]) -> RunRequest | None:
        run = record.dagster_run
        partition = run.tags.get("dagster/partition")
        if partition is None:
            return None
        team_id = self._eligible_team(partition)
        if team_id is None:
            return None
        try:
            attempt = int(run.tags.get(RETRY_ATTEMPT_TAG, "0"))
        except ValueError:
            return None
        latest = self.context.instance.get_runs(
            filters=RunsFilter(job_name=self.job_name, tags={"dagster/partition": partition}), limit=1
        )
        if not latest or latest[0].run_id != run.run_id or latest[0].status != DagsterRunStatus.FAILURE:
            return None

        exhausted = attempt >= len(RETRY_DELAYS) or attempt < 0 or not self._is_safe_to_replay(record)
        retry_at = None
        if not exhausted:
            # Stable jitter keeps repeated evaluations from moving the retry deadline.
            delay = RETRY_DELAYS[attempt] * random.Random(run.run_id).uniform(0.8, 1.2)
            retry_at = datetime.fromtimestamp(record.end_time or record.update_timestamp.timestamp(), UTC) + timedelta(
                seconds=delay
            )
        record_backfill_recovery(
            team_id=team_id,
            dataset=self.dataset,
            partition_key=partition,
            run_id=run.run_id,
            retry_at=retry_at,
            exhausted=exhausted,
            previous_run_id=run.tags.get(RETRY_OF_TAG),
        )
        if retry_at is None or retry_at > timezone.now():
            return None

        # Overlapping exports both replace the same DuckLake rows.
        for active in active_partitions:
            if active.split("_", 1)[0] == str(team_id) and (
                "_" not in active
                or "_" not in partition
                or active.startswith(partition)
                or partition.startswith(active)
            ):
                return None
        active_partitions.add(partition)
        return RunRequest(
            job_name=self.job_name,
            partition_key=partition,
            run_key=f"recover:{run.run_id}",
            run_config=run.run_config,
            tags={
                RECOVERY_TAG: "true",
                RETRY_ATTEMPT_TAG: str(attempt + 1),
                RETRY_OF_TAG: run.run_id,
                **({"duckling_backfill_type": "full"} if run.tags.get("duckling_backfill_type") == "full" else {}),
            },
        )

    def evaluate(self, cursor: str | None) -> tuple[list[RunRequest], str | None]:
        _repair_stale_running_statuses(self.context, self.dataset)
        records = self.context.instance.get_run_records(
            filters=RunsFilter(job_name=self.job_name, statuses=[DagsterRunStatus.FAILURE]),
            cursor=cursor,
            limit=SCAN_LIMIT,
        )
        active = self.context.instance.get_runs(
            filters=RunsFilter(job_name=self.job_name, statuses=INFLIGHT_STATUSES),
            limit=EVENTS_BACKFILL_TARGET_QUEUE_DEPTH + 1,
        )
        slots = max(
            0,
            min(
                EVENTS_BACKFILL_TARGET_QUEUE_DEPTH - len(active),
                MAX_INFLIGHT_RECOVERIES - sum(run.tags.get(RECOVERY_TAG) == "true" for run in active),
            ),
        )
        active_partitions = {run.tags["dagster/partition"] for run in active if "dagster/partition" in run.tags}
        requests: list[RunRequest] = []
        for record in records:
            if len(requests) >= slots:
                break
            if request := self._request(record, active_partitions):
                requests.append(request)
        next_cursor = records[-1].dagster_run.run_id if len(records) == SCAN_LIMIT else None
        return requests, next_cursor


@sensor(
    jobs=[duckling_events_backfill_job, duckling_persons_backfill_job],
    minimum_interval_seconds=60,
    default_status=DefaultSensorStatus.RUNNING,
)
def duckling_backfill_recovery_sensor(context: SensorEvaluationContext) -> SensorResult:
    enabled_teams = {
        membership.team_id for membership in list_enabled_backfill_team_memberships("backfill_recovery_sensor")
    }
    if not enabled_teams:
        return SensorResult(run_requests=[])
    cursors = json.loads(context.cursor) if context.cursor else {}
    requests: list[RunRequest] = []
    for dataset in ("events", "persons"):
        recovery = BackfillRecovery(context, dataset, enabled_teams)
        dataset_requests, cursors[dataset] = recovery.evaluate(cursors.get(dataset))
        requests.extend(dataset_requests)
    return SensorResult(run_requests=requests, cursor=json.dumps(cursors))
