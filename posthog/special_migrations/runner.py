from datetime import datetime

from posthog.celery import app
from posthog.models.special_migration import MigrationStatus, SpecialMigration
from posthog.models.utils import UUIDT
from posthog.special_migrations.setup import ALL_SPECIAL_MIGRATIONS


# select for update?
def start_special_migration(migration_name: str) -> bool:
    migration_instance = SpecialMigration.objects.get(name=migration_name)
    if not migration_instance or migration_instance.status == MigrationStatus.Running:
        return False

    migration_definition = ALL_SPECIAL_MIGRATIONS[migration_name]

    for service_version_requirement in migration_definition.service_version_requirements:
        [in_range, version] = service_version_requirement.is_service_in_accepted_version()
        if not in_range:
            process_error(
                migration_instance,
                f"Service {service_version_requirement.service} is in version {version}. Expected range: {str(service_version_requirement.supported_version)}.",
            )

    ok, error = migration_definition.healthcheck()
    if not ok:
        process_error(migration_instance, error)
        return

    migration_instance.status = MigrationStatus.Running
    migration_instance.started_at = datetime.now()
    migration_instance.save()
    return run_special_migration_next_op(migration_name, migration_instance)


def run_special_migration_next_op(migration_name: str, migration_instance: SpecialMigration = None):
    migration_instance = migration_instance or SpecialMigration.objects.get(
        name=migration_name, status=MigrationStatus.Running
    )

    if not migration_instance:
        return False

    migration_definition = ALL_SPECIAL_MIGRATIONS[migration_name]
    if migration_instance.current_operation_index > len(migration_definition.operations) - 1:
        migration_instance.status = MigrationStatus.CompletedSuccessfully
        migration_instance.finished_at = datetime.now()
        migration_instance.progress = 100
        migration_instance.save()
        return True

    op = migration_definition.operations[migration_instance.current_operation_index]

    error = None
    current_query_id = str(UUIDT())

    try:
        execute_op(op.database, op.sql, op.timeout_seconds, current_query_id)
        migration_instance.current_query_id = current_query_id
        migration_instance.current_operation_index += 1
    except Exception as e:
        error = str(e)
        process_error(migration_instance, error)

    migration_instance.save()

    if error:
        return False

    update_migration_progress(migration_name)

    return run_special_migration_next_op(migration_name, migration_instance)


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
    migration_instance.error = error
    migration_instance.finished_at = datetime.now()

    attempt_migration_rollback(migration_instance)

    migration_instance.save()


def run_migration_healthcheck(migration_instance: SpecialMigration):
    return ALL_SPECIAL_MIGRATIONS[migration_instance.name].healthcheck()


def update_migration_progress(migration_instance: SpecialMigration):
    try:
        migration_instance.progress = ALL_SPECIAL_MIGRATIONS[migration_instance.name].progress(migration_instance)
        migration_instance.save()
    except:
        pass


def attempt_migration_rollback(migration_instance: SpecialMigration, force: bool = False):
    error = None
    try:
        rollback = ALL_SPECIAL_MIGRATIONS[migration_instance.name].rollback
        ok, error = rollback(migration_instance)
        if ok:
            migration_instance.status = MigrationStatus.RolledBack
            migration_instance.save()
            return

    except Exception as e:
        error = str(e)

    if error and force:
        migration_instance.status = MigrationStatus.Errored
        migration_instance.error = f"Force rollback failed with error: {error}"
        migration_instance.save()


def trigger_migration(migration_instance: SpecialMigration):
    from posthog.tasks.special_migrations import run_special_migration

    task = run_special_migration.delay(migration_instance.name)
    migration_instance.celery_task_id = str(task.id)
    migration_instance.save()


# DANGEROUS! Can cause another task to be lost
def force_stop_migration(migration_instance: SpecialMigration, error: str = "Force stopped by user"):
    app.control.revoke(migration_instance.celery_task_id, terminate=True)
    process_error(migration_instance, error)


def force_rollback_migration(migration_instance: SpecialMigration):
    attempt_migration_rollback(migration_instance, force=True)
