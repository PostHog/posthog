from datetime import datetime
from typing import Optional

from semantic_version.base import SimpleSpec

from posthog.celery import app
from posthog.models.special_migration import MigrationStatus, SpecialMigration, get_all_running_special_migrations
from posthog.models.utils import UUIDT
from posthog.special_migrations.setup import ALL_SPECIAL_MIGRATIONS, POSTHOG_VERSION, SPECIAL_MIGRATION_TO_DEPENDENCY
from posthog.special_migrations.utils import execute_op, mark_migration_as_successful, process_error, trigger_migration

# important to prevent us taking up too many celery workers
# and running migrations sequentially
MAX_CONCURRENT_SPECIAL_MIGRATIONS = 1

# select for update?
def start_special_migration(migration_name: str) -> bool:
    migration_instance = SpecialMigration.objects.get(name=migration_name)
    over_concurrent_migrations_limit = len(get_all_running_special_migrations()) >= MAX_CONCURRENT_SPECIAL_MIGRATIONS
    if (
        not migration_instance
        or over_concurrent_migrations_limit
        or not is_migration_in_range(migration_instance.posthog_min_version, migration_instance.posthog_max_version)
        or migration_instance.status == MigrationStatus.Running
    ):
        return False

    migration_definition = ALL_SPECIAL_MIGRATIONS[migration_name]

    if not migration_definition.is_required():
        mark_migration_as_successful(migration_instance)
        return False

    for service_version_requirement in migration_definition.service_version_requirements:
        [in_range, version] = service_version_requirement.is_service_in_accepted_version()
        if not in_range:
            process_error(
                migration_instance,
                f"Service {service_version_requirement.service} is in version {version}. Expected range: {str(service_version_requirement.supported_version)}.",
            )

    ok, error = run_migration_healthcheck(migration_instance)
    if not ok:
        process_error(migration_instance, error)
        return False

    migration_instance.last_error = ""
    migration_instance.current_query_id = ""
    migration_instance.celery_task_id = ""
    migration_instance.progress = 0
    migration_instance.current_operation_index = 0
    migration_instance.status = MigrationStatus.Running
    migration_instance.started_at = datetime.now()
    migration_instance.finished_at = None
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
        mark_migration_as_successful(migration_instance)
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
    # we don't want to interrupt a migration if the progress check fails, hence try without handling exceptions
    try:
        migration_instance.progress = ALL_SPECIAL_MIGRATIONS[migration_instance.name].progress(migration_instance)  # type: ignore
        migration_instance.save()
    except:
        pass


# TODO: Move towards a rollback per op
def attempt_migration_rollback(migration_instance: SpecialMigration, force: bool = False):
    error = None
    try:
        rollback = ALL_SPECIAL_MIGRATIONS[migration_instance.name].rollback
        ok, error = rollback(migration_instance)  # type: ignore
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
    migration_definition = ALL_SPECIAL_MIGRATIONS[migration_instance.name]
    index = migration_instance.current_operation_index
    return migration_definition.operations[index].resumbale


def is_migration_in_range(posthog_min_version, posthog_max_version):
    return POSTHOG_VERSION in SimpleSpec(f">={posthog_min_version},<={posthog_max_version}")


def run_next_migration(candidate: str) -> bool:
    migration_instance = SpecialMigration.objects.get(name=candidate)
    migration_in_range = is_migration_in_range(
        migration_instance.posthog_min_version, migration_instance.posthog_max_version
    )
    dependency = SPECIAL_MIGRATION_TO_DEPENDENCY[candidate]

    dependency_ok = (
        not dependency or SpecialMigration.objects.get(name=dependency).status == MigrationStatus.CompletedSuccessfully
    )

    if dependency_ok and migration_in_range and migration_instance.status == MigrationStatus.NotStarted:
        trigger_migration(migration_instance)
        return True

    return False
