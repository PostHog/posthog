from datetime import datetime
from typing import Optional

from posthog.celery import app
from posthog.models.special_migration import MigrationStatus, SpecialMigration
from posthog.models.utils import UUIDT
from posthog.special_migrations.setup import ALL_SPECIAL_MIGRATIONS
from posthog.special_migrations.utils import execute_op, process_error


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
        return False

    migration_instance.status = MigrationStatus.Running
    migration_instance.started_at = datetime.now()
    migration_instance.save()
    return run_special_migration_next_op(migration_name, migration_instance)


def run_special_migration_next_op(migration_name: str, migration_instance: Optional[SpecialMigration] = None):
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

    update_migration_progress(migration_instance)

    return run_special_migration_next_op(migration_name, migration_instance)


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
        migration_instance.last_error = f"Force rollback failed with error: {error}"
        migration_instance.save()


def is_current_operation_resumable(migration_instance: SpecialMigration):
    return (
        ALL_SPECIAL_MIGRATIONS[migration_instance.name].operations[migration_instance.current_operation_index].resumbale
    )
