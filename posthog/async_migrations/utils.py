import asyncio
from datetime import datetime
from typing import Optional

import posthoganalytics
import structlog
from django.conf import settings
from django.db import transaction
from django.utils.timezone import now

from posthog.async_migrations.definition import AsyncMigrationOperation
from posthog.async_migrations.setup import DEPENDENCY_TO_ASYNC_MIGRATION
from posthog.celery import app
from posthog.client import make_ch_pool, sync_execute
from posthog.email import is_email_available
from posthog.models.async_migration import AsyncMigration, AsyncMigrationError, MigrationStatus
from posthog.models.instance_setting import get_instance_setting
from posthog.models.user import User
from posthog.settings import (
    ASYNC_MIGRATIONS_DEFAULT_TIMEOUT_SECONDS,
    CLICKHOUSE_ALLOW_PER_SHARD_EXECUTION,
    CLICKHOUSE_CLUSTER,
    TEST,
)
from posthog.utils import get_machine_id

logger = structlog.get_logger(__name__)

SLEEP_TIME_SECONDS = 20


def send_analytics_to_posthog(event, data):
    posthoganalytics.project_api_key = "sTMFPsFhdP1Ssg"
    user = User.objects.filter(is_active=True).first()
    groups = {"instance": settings.SITE_URL}
    if user and user.current_organization:
        data["organization_name"] = user.current_organization.name
        groups["organization"] = str(user.current_organization.id)
    posthoganalytics.capture(
        get_machine_id(), event, data, groups=groups,
    )


def execute_op(op: AsyncMigrationOperation, uuid: str, rollback: bool = False):
    """
    Execute the fn or rollback_fn
    """
    op.rollback_fn(uuid) if rollback else op.fn(uuid)


def execute_op_clickhouse(
    sql: str,
    args=None,
    *,
    query_id: str,
    timeout_seconds: int = settings.ASYNC_MIGRATIONS_DEFAULT_TIMEOUT_SECONDS,
    settings=None,
    # If True, query is run on each shard.
    per_shard=False,
):
    from posthog import client

    client._request_information = {"kind": "async_migration", "id": query_id}
    settings = settings if settings else {"max_execution_time": timeout_seconds}

    try:
        if per_shard:
            execute_on_each_shard(sql, args, settings=settings)
        else:
            client.sync_execute(sql, args, settings=settings)
    except Exception as e:
        client._request_information = None
        raise Exception(f"Failed to execute ClickHouse op: sql={sql},\nquery_id={query_id},\nexception={str(e)}")

    client._request_information = None


def execute_on_each_shard(sql, args, settings=None) -> None:
    """
    Executes query on each shard separately (if enabled) or on the cluster as a whole (if not enabled).

    Note that the shard selection is stable - subsequent queries are guaranteed to hit the same shards!
    """
    if "{on_cluster_clause}" not in sql:
        raise Exception("SQL must include {on_cluster_clause} to allow execution on each shard")

    if CLICKHOUSE_ALLOW_PER_SHARD_EXECUTION:
        sql = sql.format(on_cluster_clause="")
    else:
        sql = sql.format(on_cluster_clause=f"ON CLUSTER '{CLICKHOUSE_CLUSTER}'")

    for _, _, connection in _get_all_shard_connections():
        connection.execute(sql, args, settings=settings)


def execute_on_all_shards_in_parallel(sql: str, args=None, settings=None) -> None:
    loop = asyncio.get_event_loop()

    async def run_on_all_shards():
        tasks = []
        for _, _, connection in _get_all_shard_connections():
            tasks.append(asyncio.create_task(connection.execute(sql, args, settings=settings)))

        await asyncio.wait(tasks)

    loop.run_until_complete(run_on_all_shards())
    loop.close()


def _get_all_shard_connections():
    from posthog.client import ch_pool as default_ch_pool

    if CLICKHOUSE_ALLOW_PER_SHARD_EXECUTION:
        rows = sync_execute(
            """
            SELECT shard_num, min(host_name) as host_name
            FROM system.clusters
            WHERE cluster = %(cluster)s
            GROUP BY shard_num
            ORDER BY shard_num
            """,
            {"cluster": CLICKHOUSE_CLUSTER},
        )
        for shard, host in rows:
            ch_pool = make_ch_pool(host=host)
            with ch_pool.get_client() as connection:
                yield shard, host, connection
    else:
        with default_ch_pool.get_client() as connection:
            yield None, None, connection


def execute_op_postgres(sql: str, query_id: str):
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute(f"/* {query_id} */ " + sql)
    except Exception as e:
        raise Exception(f"Failed to execute postgres op: sql={sql},\nquery_id={query_id},\nexception={str(e)}")


def _get_number_running_on_cluster(query_pattern: str) -> int:
    return sync_execute(
        """
        SELECT count()
        FROM clusterAllReplicas(%(cluster)s, system, 'processes')
        WHERE query LIKE %(query_pattern)s
        """,
        {"cluster": CLICKHOUSE_CLUSTER, "query_pattern": query_pattern},
    )[0][0]


def _sleep_until_finished(query_pattern: str) -> None:
    from time import sleep

    while _get_number_running_on_cluster(query_pattern) > 0:
        logger.debug("Query still running, waiting until it's complete", query_pattern=query_pattern)
        sleep(SLEEP_TIME_SECONDS)


def run_optimize_table(unique_name: str, query_id: str, table_name: str, deduplicate=False, final=False):
    """
    Runs the passed OPTIMIZE TABLE query.

    Note that this handles process restarts gracefully: If the query is still running on the cluster,
    we'll wait for that to complete first.
    """
    if not TEST and _get_number_running_on_cluster(f"%%optimize:{unique_name}%%") > 0:
        _sleep_until_finished(f"%%optimize:{unique_name}%%")
    else:
        final_clause = "FINAL" if final else ""
        deduplicate_clause = "DEDUPLICATE" if deduplicate else ""
        on_cluster_clause = "{on_cluster_clause}"
        sql = f"OPTIMIZE TABLE {table_name} {on_cluster_clause} {final_clause} {deduplicate_clause}"
        execute_op_clickhouse(
            sql,
            query_id=f"optimize:{unique_name}/{query_id}",
            settings={"max_execution_time": ASYNC_MIGRATIONS_DEFAULT_TIMEOUT_SECONDS, "mutations_sync": 2},
            per_shard=True,
        )


def process_error(
    migration_instance: AsyncMigration,
    error: str,
    rollback: bool = True,
    alert: bool = False,
    status: int = MigrationStatus.Errored,
    current_operation_index: Optional[int] = None,
):
    logger.error(f"Async migration {migration_instance.name} error: {error}")

    update_async_migration(
        migration_instance=migration_instance,
        current_operation_index=current_operation_index,
        status=status,
        error=error,
        finished_at=now(),
    )
    send_analytics_to_posthog(
        "Async migration error",
        {
            "name": migration_instance.name,
            "error": error,
            "current_operation_index": migration_instance.current_operation_index
            if current_operation_index is None
            else current_operation_index,
        },
    )

    if alert:
        if async_migrations_emails_enabled():
            from posthog.tasks.email import send_async_migration_errored_email

            send_async_migration_errored_email.delay(
                migration_key=migration_instance.name, time=now().isoformat(), error=error
            )

    if (
        not rollback
        or status == MigrationStatus.FailedAtStartup
        or get_instance_setting("ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK")
    ):
        return

    from posthog.async_migrations.runner import attempt_migration_rollback

    attempt_migration_rollback(migration_instance)


def trigger_migration(migration_instance: AsyncMigration, fresh_start: bool = True):
    from posthog.tasks.async_migrations import run_async_migration

    task = run_async_migration.delay(migration_instance.name, fresh_start)

    update_async_migration(
        migration_instance=migration_instance, celery_task_id=str(task.id),
    )


def force_stop_migration(
    migration_instance: AsyncMigration, error: str = "Force stopped by user", rollback: bool = True
):
    """
    In theory this is dangerous, as it can cause another task to be lost
    `revoke` with `terminate=True` kills the process that's working on the task
    and there's no guarantee the task will not already be done by the time this happens.
    See: https://docs.celeryproject.org/en/stable/reference/celery.app.control.html#celery.app.control.Control.revoke
    However, this is generally ok for us because:
    1. Given these are long-running migrations, it is statistically unlikely it will complete during in between
    this call and the time the process is killed
    2. Our Celery tasks are not essential for the functioning of PostHog, meaning losing a task is not the end of the world
    """

    app.control.revoke(migration_instance.celery_task_id, terminate=True)
    process_error(migration_instance, error, rollback=rollback)


def rollback_migration(migration_instance: AsyncMigration):
    from posthog.async_migrations.runner import attempt_migration_rollback

    attempt_migration_rollback(migration_instance)


def complete_migration(migration_instance: AsyncMigration, email: bool = True):
    finished_at = now()

    migration_instance.refresh_from_db()

    needs_update = migration_instance.status != MigrationStatus.CompletedSuccessfully

    if needs_update:
        update_async_migration(
            migration_instance=migration_instance,
            status=MigrationStatus.CompletedSuccessfully,
            finished_at=finished_at,
            progress=100,
        )
        send_analytics_to_posthog("Async migration completed", {"name": migration_instance.name})

        if email and async_migrations_emails_enabled():
            from posthog.tasks.email import send_async_migration_complete_email

            send_async_migration_complete_email.delay(
                migration_key=migration_instance.name, time=finished_at.isoformat()
            )

    if get_instance_setting("AUTO_START_ASYNC_MIGRATIONS"):
        next_migration = DEPENDENCY_TO_ASYNC_MIGRATION.get(migration_instance.name)
        if next_migration:
            from posthog.async_migrations.runner import run_next_migration

            run_next_migration(next_migration)


def mark_async_migration_as_running(migration_instance: AsyncMigration):
    update_async_migration(
        migration_instance=migration_instance,
        current_query_id="",
        progress=0,
        current_operation_index=0,
        status=MigrationStatus.Running,
        started_at=now(),
        finished_at=None,
    )


def update_async_migration(
    migration_instance: AsyncMigration,
    error: Optional[str] = None,
    current_query_id: Optional[str] = None,
    celery_task_id: Optional[str] = None,
    progress: Optional[int] = None,
    current_operation_index: Optional[int] = None,
    status: Optional[int] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
    lock_row: bool = True,
):
    def execute_update():
        instance = migration_instance
        if lock_row:
            instance = AsyncMigration.objects.select_for_update().get(pk=migration_instance.pk)
        else:
            instance.refresh_from_db()
        if error is not None:
            AsyncMigrationError.objects.create(async_migration=instance, description=error).save()
        if current_query_id is not None:
            instance.current_query_id = current_query_id
        if celery_task_id is not None:
            instance.celery_task_id = celery_task_id
        if progress is not None:
            instance.progress = progress
        if current_operation_index is not None:
            instance.current_operation_index = current_operation_index
        if status is not None:
            instance.status = status
        if started_at is not None:
            instance.started_at = started_at
        if finished_at is not None:
            instance.finished_at = finished_at
        instance.save()

    if lock_row:
        with transaction.atomic():
            execute_update()
    else:
        execute_update()


def async_migrations_emails_enabled():
    return is_email_available() and not get_instance_setting("ASYNC_MIGRATIONS_OPT_OUT_EMAILS")
