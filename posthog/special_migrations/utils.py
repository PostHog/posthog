from datetime import datetime
from typing import Optional

from django.db import transaction

from posthog.celery import app
from posthog.constants import AnalyticsDBMS
from posthog.models.special_migration import MigrationStatus, SpecialMigration
from posthog.special_migrations.setup import DEPENDENCY_TO_SPECIAL_MIGRATION


def execute_op(database: AnalyticsDBMS, sql: str, timeout_seconds: int, query_id: str):
    if database == AnalyticsDBMS.CLICKHOUSE:
        execute_op_clickhouse(sql, query_id, timeout_seconds)
        return

    execute_op_postgres(sql, query_id)


def execute_op_clickhouse(sql: str, query_id: str, timeout_seconds: int):
    from ee.clickhouse.client import sync_execute

    sync_execute(f"/* {query_id} */ " + sql, settings={"max_execution_time": timeout_seconds})


def execute_op_postgres(sql: str, query_id: str):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(f"/* {query_id} */ " + sql)


def process_error(migration_instance: SpecialMigration, error: Optional[str]):
    update_special_migration(
        migration_instance=migration_instance,
        status=MigrationStatus.Errored,
        last_error=error or "",
        finished_at=datetime.now(),
        lock_row=True,
    )

    from posthog.special_migrations.runner import attempt_migration_rollback

    attempt_migration_rollback(migration_instance)


def trigger_migration(migration_instance: SpecialMigration, fresh_start=True):
    from posthog.tasks.special_migrations import run_special_migration

    task = run_special_migration.delay(migration_instance.name, fresh_start)

    update_special_migration(
        migration_instance=migration_instance, celery_task_id=str(task.id),
    )


# DANGEROUS! Can cause another task to be lost
def force_stop_migration(migration_instance: SpecialMigration, error: str = "Force stopped by user"):
    app.control.revoke(migration_instance.celery_task_id, terminate=True)
    process_error(migration_instance, error)


def force_rollback_migration(migration_instance: SpecialMigration):
    from posthog.special_migrations.runner import attempt_migration_rollback

    attempt_migration_rollback(migration_instance, force=True)


def complete_migration(migration_instance: SpecialMigration):
    update_special_migration(
        migration_instance=migration_instance,
        status=MigrationStatus.CompletedSuccessfully,
        finished_at=datetime.now(),
        progress=100,
        lock_row=True,
    )

    from posthog.special_migrations.runner import run_next_migration

    next_migration = DEPENDENCY_TO_SPECIAL_MIGRATION.get(migration_instance.name)

    if next_migration:
        run_next_migration(next_migration)


def reset_special_migration(migration_instance: SpecialMigration):
    update_special_migration(
        migration_instance=migration_instance,
        last_error="",
        current_query_id="",
        celery_task_id="",
        progress=0,
        current_operation_index=0,
        status=MigrationStatus.Running,
        started_at=datetime.now(),
        finished_at=None,
    )


def update_special_migration(
    migration_instance: SpecialMigration,
    last_error: Optional[str] = None,
    current_query_id: Optional[str] = None,
    celery_task_id: Optional[str] = None,
    progress: Optional[int] = None,
    current_operation_index: Optional[int] = None,
    status: Optional[MigrationStatus] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
    lock_row=False,
):
    def execute_update():
        instance = migration_instance
        if lock_row:
            instance = SpecialMigration.objects.select_for_update().get(pk=migration_instance.pk)
        else:
            instance.refresh_from_db()
        if last_error:
            instance.last_error = last_error
        if current_query_id:
            instance.current_query_id = current_query_id
        if celery_task_id:
            instance.celery_task_id = celery_task_id
        if progress:
            instance.progress = progress
        if current_operation_index:
            instance.current_operation_index = current_operation_index
        if status:
            instance.status = status
        if started_at:
            instance.started_at = started_at
        if finished_at:
            instance.finished_at = finished_at
        instance.save()

    if lock_row:
        with transaction.atomic():
            execute_update()
    else:
        execute_update()
