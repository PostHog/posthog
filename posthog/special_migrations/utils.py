from datetime import datetime

from posthog.celery import app
from posthog.models.special_migration import MigrationStatus, SpecialMigration


def execute_op(database: str, sql: str, timeout_seconds: int, query_id: str):
    if database == "clickhouse":
        execute_op_clickhouse(sql, query_id, timeout_seconds)
        return

    execute_op_postgres(sql, query_id)


def execute_op_clickhouse(sql: str, query_id: str, timeout_seconds: int):
    from ee.clickhouse.client import sync_execute

    sync_execute(f"/* {query_id} */" + sql, settings={"max_execution_time": timeout_seconds})


def execute_op_postgres(sql: str, query_id: str):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(f"/* {query_id} */" + sql)


def process_error(migration_instance: SpecialMigration, error: str):
    migration_instance.status = MigrationStatus.Errored
    migration_instance.last_error = error
    migration_instance.finished_at = datetime.now()

    from posthog.special_migrations.runner import attempt_migration_rollback

    attempt_migration_rollback(migration_instance)

    migration_instance.save()


def trigger_migration(migration_instance: SpecialMigration, fresh_start=True):
    from posthog.tasks.special_migrations import run_special_migration

    task = run_special_migration.delay(migration_instance.name, fresh_start)
    migration_instance.celery_task_id = str(task.id)
    migration_instance.save()


# DANGEROUS! Can cause another task to be lost
def force_stop_migration(migration_instance: SpecialMigration, error: str = "Force stopped by user"):
    app.control.revoke(migration_instance.celery_task_id, terminate=True)
    process_error(migration_instance, error)


def force_rollback_migration(migration_instance: SpecialMigration):
    from posthog.special_migrations.runner import attempt_migration_rollback

    attempt_migration_rollback(migration_instance, force=True)


def mark_migration_as_successful(migration_instance: SpecialMigration):
    migration_instance.status = MigrationStatus.CompletedSuccessfully
    migration_instance.finished_at = datetime.now()
    migration_instance.progress = 100
    migration_instance.save()
