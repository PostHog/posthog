"""Helpers for a daily rollup that builds one UTC day into a staging table and publishes it by partition swap."""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta

from django.conf import settings

import dagster
import dagster_slack

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.common import JobOwners, settings_with_log_comment
from posthog.dags.common.common import EXECUTING_RUN_STATUSES, describe_runs
from posthog.dags.slack_alerts import notification_channel_per_team, send_slack_alert

from products.web_analytics.dags.web_preaggregated_utils import (
    get_partitions,
    swap_partitions_from_staging,
    sync_partitions_on_replicas,
)

DEPLOYED_CLOUD_REGIONS = ("US", "EU", "DEV")
ONE_GIB = 1024**3
SPILL_GROUP_BY_AFTER_BYTES = 2 * ONE_GIB
MAX_THREADS = 8
STUCK_RUN_AGE = timedelta(hours=3)
PARTITION_ID_FORMAT = "%Y%m%d"


def query_log_clusters() -> tuple[str, ...]:
    # Tagged queries, warehouse reads and endpoint runs among them, run on the main, logs and endpoints clusters
    # in the cloud. Local stacks have only the main one.
    if settings.CLOUD_DEPLOYMENT in DEPLOYED_CLOUD_REGIONS:
        return (settings.CLICKHOUSE_CLUSTER, "logs", "endpoints")
    return (settings.CLICKHOUSE_CLUSTER,)


def query_log_source(columns: str) -> str:
    # system.query_log keeps 14 days on each replica.
    branches = " UNION ALL ".join(
        f"SELECT {columns} FROM clusterAllReplicas('{cluster}', system.query_log)" for cluster in query_log_clusters()
    )
    return f"({branches})"


def day_query_parameters(day: date) -> dict[str, date | datetime | str]:
    day_start = datetime.combine(day, time.min)
    return {
        "day": day,
        "day_start": day_start,
        "day_end": day_start + timedelta(days=1),
    }


def rollup_query_settings(context: dagster.OpExecutionContext) -> dict[str, str | int]:
    return {
        **settings_with_log_comment(context),
        "max_bytes_before_external_group_by": SPILL_GROUP_BY_AFTER_BYTES,
        "max_threads": MAX_THREADS,
    }


def refuse_to_run_beside_another_rollup(context: dagster.OpExecutionContext) -> None:
    others = describe_runs(
        context.instance,
        (context.job_name,),
        statuses=EXECUTING_RUN_STATUSES,
        created_after=datetime.now(UTC) - STUCK_RUN_AGE,
        exclude_run_id=context.run_id,
    )
    if others:
        raise dagster.Failure(
            description=f"{'; '.join(others)} is executing, and every run shares one staging table. "
            "Wait for that run to finish, then run this day again."
        )


def publish_staged_day(
    context: dagster.OpExecutionContext,
    cluster: ClickhouseCluster,
    day: date,
    *,
    table: str,
    staging_table: str,
    node_role: NodeRole,
) -> bool:
    """Swap the staged day into the published table. Returns False and publishes nothing when staging is empty."""
    sync_partitions_on_replicas(context, cluster, staging_table, node_role=node_role)
    staged_partitions = get_partitions(
        context,
        cluster,
        staging_table,
        filter_by_partition_window=True,
        node_role=node_role,
    )
    day_partition = day.strftime(PARTITION_ID_FORMAT)
    if staged_partitions == [day_partition]:
        swap_partitions_from_staging(context, cluster, table, staging_table, node_role=node_role)
        return True
    if staged_partitions:
        raise dagster.Failure(
            description=f"Staging holds partitions {staged_partitions}, not only {day_partition}. "
            "Nothing was published."
        )
    return False


def has_published_day(instance: dagster.DagsterInstance, job_name: str, day: date) -> bool:
    return bool(
        instance.get_run_records(
            dagster.RunsFilter(
                job_name=job_name,
                statuses=[dagster.DagsterRunStatus.SUCCESS],
                tags={"dagster/partition": day.isoformat()},
            ),
            limit=1,
        )
    )


def unpublished_days(
    instance: dagster.DagsterInstance, *, job_name: str, start_date: str, catch_up_days: int, today: date
) -> list[date]:
    first_day = max(date.fromisoformat(start_date), today - timedelta(days=catch_up_days))
    days = (first_day + timedelta(days=offset) for offset in range((today - first_day).days))
    return [day for day in days if not has_published_day(instance, job_name, day)]


def build_catch_up_schedule(
    job: dagster.JobDefinition,
    *,
    start_date: str,
    attempt_hours_utc: Sequence[int],
    catch_up_days: int,
) -> dagster.ScheduleDefinition:
    """Requests the newest unpublished day of the catch-up window at each attempt hour."""

    @dagster.schedule(
        job=job,
        name=f"{job.name}_schedule",
        cron_schedule=f"0 {','.join(str(hour) for hour in attempt_hours_utc)} * * *",
        execution_timezone="UTC",
        default_status=dagster.DefaultScheduleStatus.RUNNING,
    )
    def catch_up_schedule(context: dagster.ScheduleEvaluationContext) -> dagster.RunRequest | dagster.SkipReason:
        active_runs = describe_runs(
            context.instance,
            (job.name,),
            created_after=datetime.now(UTC) - STUCK_RUN_AGE,
            exclude_run_id="",
        )
        if active_runs:
            return dagster.SkipReason(f"{'; '.join(active_runs)} is queued or executing.")
        missing_days = unpublished_days(
            context.instance,
            job_name=job.name,
            start_date=start_date,
            catch_up_days=catch_up_days,
            today=datetime.now(UTC).date(),
        )
        if not missing_days:
            return dagster.SkipReason(f"Every day of the last {catch_up_days} days is published.")
        return dagster.RunRequest(partition_key=missing_days[-1].isoformat())

    return catch_up_schedule


def build_overdue_sensor(
    job: dagster.JobDefinition,
    *,
    name: str,
    owner: JobOwners,
    start_date: str,
    attempt_hours_utc: Sequence[int],
    catch_up_days: int,
    overdue_after_utc: time,
    check_interval_seconds: int,
) -> dagster.SensorDefinition:
    """Alerts the owner's channel once a day when a day of the catch-up window has no successful run."""

    @dagster.sensor(
        name=name,
        minimum_interval_seconds=check_interval_seconds,
        default_status=dagster.DefaultSensorStatus.RUNNING,
    )
    def overdue_sensor(
        context: dagster.SensorEvaluationContext, slack: dagster_slack.SlackResource
    ) -> dagster.SkipReason | None:
        now = datetime.now(UTC)
        if now.time() < overdue_after_utc:
            return dagster.SkipReason(f"The rollup is not overdue before {overdue_after_utc} UTC.")
        today = now.date()
        if context.cursor == today.isoformat():
            return dagster.SkipReason(f"Already alerted about missing days on {today}.")
        missing_days = unpublished_days(
            context.instance, job_name=job.name, start_date=start_date, catch_up_days=catch_up_days, today=today
        )
        if not missing_days:
            return dagster.SkipReason(f"Every day of the last {catch_up_days} days is published.")
        missing = ", ".join(day.isoformat() for day in missing_days)
        if not settings.CLOUD_DEPLOYMENT:
            return dagster.SkipReason(f"{missing} is missing, but alerts only go out in cloud deployments.")

        attempt_times = ", ".join(f"{hour:02d}:00" for hour in attempt_hours_utc)
        job_url = f"https://{settings.DAGSTER_DOMAIN}/locations/clickhouse/jobs/{job.name}"
        message = (
            f":hourglass: `{job.name}` has no successful run for {missing} "
            f"by {overdue_after_utc:%H:%M} UTC. The schedule retries missing days at {attempt_times} UTC "
            f"until they are {catch_up_days} days old. Check that its schedule is running and that no run is stuck in the queue: "
            f"<{job_url}|View in Dagster>\nEnvironment: {settings.CLOUD_DEPLOYMENT}"
        )
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": message}}]
        channel = notification_channel_per_team[owner.value]
        if send_slack_alert(context, slack.get_client(), channel, blocks, message):
            context.update_cursor(today.isoformat())
        return None

    return overdue_sensor
