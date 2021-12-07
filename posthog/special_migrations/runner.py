from datetime import datetime
from typing import Optional, Tuple

from semantic_version.base import SimpleSpec

from posthog.models.special_migration import MigrationStatus, SpecialMigration, get_all_running_special_migrations
from posthog.models.utils import UUIDT
from posthog.special_migrations.setup import (
    POSTHOG_VERSION,
    get_special_migration_definition,
    get_special_migration_dependency,
)
from posthog.special_migrations.utils import (
    execute_op,
    mark_migration_as_successful,
    process_error,
    reset_special_migration,
    trigger_migration,
)

# important to prevent us taking up too many celery workers
# and running migrations sequentially
MAX_CONCURRENT_SPECIAL_MIGRATIONS = 1


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

    migration_definition = get_special_migration_definition(migration_name)

    if not migration_definition.is_required():
        mark_migration_as_successful(migration_instance)
        return False

    for service_version_requirement in migration_definition.service_version_requirements:
        in_range, version = service_version_requirement.is_service_in_accepted_version()
        if not in_range:
            process_error(
                migration_instance,
                f"Service {service_version_requirement.service} is in version {version}. Expected range: {str(service_version_requirement.supported_version)}.",
            )

    ok, error = run_migration_healthcheck(migration_instance)
    if not ok:
        process_error(migration_instance, error)
        return False

    dependency_ok, dependency_name = is_migration_dependency_fulfilled(migration_instance.name)

    if not dependency_ok:
        process_error(migration_instance, f"Could not trigger migration because it depends on {dependency_name}")
        return False

    reset_special_migration(migration_instance)

    return run_special_migration_next_op(migration_name, migration_instance)


def run_special_migration_next_op(
    migration_name: str, migration_instance: Optional[SpecialMigration] = None, run_all=True
):
    migration_instance = migration_instance or SpecialMigration.objects.get(
        name=migration_name, status=MigrationStatus.Running
    )

    if not migration_instance:
        return False

    migration_definition = get_special_migration_definition(migration_name)
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

    # recursively run through all operations
    if run_all:
        return run_special_migration_next_op(migration_name, migration_instance)


def run_migration_healthcheck(migration_instance: SpecialMigration):
    return get_special_migration_definition(migration_instance.name).healthcheck()


def update_migration_progress(migration_instance: SpecialMigration):
    # we don't want to interrupt a migration if the progress check fails, hence try without handling exceptions
    try:
        migration_instance.progress = get_special_migration_definition(migration_instance.name).progress(
            migration_instance  # type: ignore
        )
        migration_instance.save()
    except:
        pass


def attempt_migration_rollback(migration_instance: SpecialMigration, force: bool = False):
    try:
        ops = get_special_migration_definition(migration_instance.name).operations
        start = migration_instance.current_operation_index
        end = -(len(ops) + 1)

        for op in ops[start:end:-1]:
            if not op.rollback:
                if op.rollback == "":
                    continue
                raise Exception(f"No rollback provided for operation {op.sql}")
            execute_op(database=op.database, sql=op.rollback, timeout_seconds=60, query_id=str(UUIDT()))
    except Exception as e:
        error = str(e)

        # forced rollbacks are when the migration completed successfully but the user
        # still requested a rollback, in which case we set the error to whatever happened
        # while rolling back. under normal circumstances, the error is reserved to
        # things that happened during the migration itself
        if force:
            migration_instance.status = MigrationStatus.Errored
            migration_instance.last_error = f"Force rollback failed with error: {error}"
            migration_instance.save()

        return

    migration_instance.status = MigrationStatus.RolledBack
    migration_instance.progress = 0
    migration_instance.save()


def is_current_operation_resumable(migration_instance: SpecialMigration):
    migration_definition = get_special_migration_definition(migration_instance.name)
    index = migration_instance.current_operation_index
    return migration_definition.operations[index].resumbale


def is_migration_in_range(posthog_min_version, posthog_max_version):
    return POSTHOG_VERSION in SimpleSpec(f">={posthog_min_version},<={posthog_max_version}")


def run_next_migration(candidate: str) -> bool:
    migration_instance = SpecialMigration.objects.get(name=candidate)
    migration_in_range = is_migration_in_range(
        migration_instance.posthog_min_version, migration_instance.posthog_max_version
    )

    dependency_ok, _ = is_migration_dependency_fulfilled(candidate)

    if dependency_ok and migration_in_range and migration_instance.status == MigrationStatus.NotStarted:
        trigger_migration(migration_instance)
        return True

    return False


def is_migration_dependency_fulfilled(migration_name: str) -> Tuple[bool, Optional[str]]:
    dependency = get_special_migration_dependency(migration_name)

    dependency_ok: bool = (
        not dependency or SpecialMigration.objects.get(name=dependency).status == MigrationStatus.CompletedSuccessfully
    )
    return dependency_ok, dependency
