from asyncio.tasks import sleep
from datetime import datetime, timedelta

from posthog.celery import app
from posthog.models.special_migration import MigrationStatus, SpecialMigration
from posthog.models.utils import UUIDT
from posthog.special_migrations.manager import ALL_SPECIAL_MIGRATIONS


# select for update?
def start_special_migration(migration_name):
    migration_instance = SpecialMigration.objects.get(name=migration_name, status=MigrationStatus.NotStarted)
    if not migration_instance:
        return False

    migration_definition = ALL_SPECIAL_MIGRATIONS[migration_name].Migration

    for service_version_requirement in migration_definition.service_version_requirements:
        [in_range, version] = service_version_requirement.is_service_in_accepted_version()
        if not in_range:
            process_error(
                migration_instance,
                f"Service {service_version_requirement.service} is in version {version}. Expected range: {str(service_version_requirement.supported_version)}.",
                migration_definition.rollback,
            )

    ok, error = migration_definition.precheck()
    if not ok:
        process_error(migration_instance, error, migration_definition.rollback)
        return

    migration_instance.status = MigrationStatus.Running
    migration_instance.started_at = datetime.now()
    migration_instance.save()
    return run_special_migration_next_op(migration_name, migration_instance)


def run_special_migration_next_op(migration_name, migration_instance=None):
    migration_instance = migration_instance or SpecialMigration.objects.get(
        name=migration_name, status=MigrationStatus.Running
    )

    if not migration_instance:
        return False

    migration_definition = ALL_SPECIAL_MIGRATIONS[migration_name].Migration
    if migration_instance.current_operation_index > len(migration_definition.operations) - 1:
        migration_instance.status = MigrationStatus.CompletedSuccessfully
        migration_instance.finished_at = datetime.now()
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
        process_error(migration_instance, error, migration_definition.rollback, False)

    migration_instance.save()

    if error:
        return False

    try:
        migration_instance.progress = migration_definition.progress()
        migration_instance.save()
    except:
        pass

    return run_special_migration_next_op(migration_name, migration_instance)


def execute_op(database, sql, timeout_seconds, query_id):
    if database == "clickhouse":
        execute_op_clickhouse(sql, query_id, timeout_seconds)
        return

    execute_op_postgres(sql, query_id)


def execute_op_clickhouse(sql, query_id, timeout_seconds):
    from ee.clickhouse.client import sync_execute

    sync_execute(f"/* {query_id} */" + sql, settings={"max_execution_time": timeout_seconds})


def execute_op_postgres(sql, query_id):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(f"/* {query_id} */" + sql)


def process_error(migration_instance, error, rollback, save=True):
    migration_instance.status = MigrationStatus.Errored
    migration_instance.error = error
    migration_instance.finished_at = datetime.now()
    try:
        success = rollback()
        if success:
            migration_instance.status = MigrationStatus.RolledBack
    except:
        pass

    if save:
        migration_instance.save()
