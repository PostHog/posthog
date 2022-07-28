from typing import List, Optional, Tuple

from semantic_version.base import SimpleSpec

from posthog.async_migrations.definition import AsyncMigrationDefinition
from posthog.async_migrations.setup import (
    POSTHOG_VERSION,
    get_async_migration_definition,
    get_async_migration_dependency,
)
from posthog.async_migrations.utils import (
    complete_migration,
    execute_op,
    mark_async_migration_as_running,
    process_error,
    send_analytics_to_posthog,
    trigger_migration,
    update_async_migration,
)
from posthog.models.async_migration import AsyncMigration, MigrationStatus, get_all_running_async_migrations
from posthog.models.utils import UUIDT
from posthog.version_requirement import ServiceVersionRequirement

"""
Important to prevent us taking up too many celery workers and also to enable running migrations sequentially
"""
MAX_CONCURRENT_ASYNC_MIGRATIONS = 1


def start_async_migration(
    migration_name: str, ignore_posthog_version=False, migration_definition: Optional[AsyncMigrationDefinition] = None
) -> bool:
    """
    Performs some basic checks to ensure the migration can indeed run, and then kickstarts the chain of operations

    Returns whether migration was successful
    Checks:
    1. We're not over the concurrent migrations limit
    2. The migration can be run with the current PostHog version
    3. The migration is not already running
    4. The migration is required given the instance configuration
    5. The service version requirements are met (e.g. X < ClickHouse version < Y)
    6. The migration's healthcheck passes
    7. The migration's dependency has been completed
    """
    send_analytics_to_posthog("Async migration start", {"name": migration_name})

    migration_instance = AsyncMigration.objects.get(name=migration_name)
    over_concurrent_migrations_limit = get_all_running_async_migrations().count() >= MAX_CONCURRENT_ASYNC_MIGRATIONS
    posthog_version_valid = ignore_posthog_version or is_posthog_version_compatible(
        migration_instance.posthog_min_version, migration_instance.posthog_max_version
    )

    if (
        not migration_instance
        or over_concurrent_migrations_limit
        or not posthog_version_valid
        or migration_instance.status == MigrationStatus.Running
    ):
        return False

    if migration_definition is None:
        migration_definition = get_async_migration_definition(migration_name)

    if not migration_definition.is_required():
        complete_migration(migration_instance, email=False)
        return True

    ok, error = check_service_version_requirements(migration_definition.service_version_requirements)
    if not ok:
        process_error(migration_instance, error, status=MigrationStatus.FailedAtStartup)
        return False

    ok, error = is_migration_dependency_fulfilled(migration_instance.name)
    if not ok:
        process_error(migration_instance, error, status=MigrationStatus.FailedAtStartup)
        return False

    ok, error = run_migration_precheck(migration_instance)
    if not ok:
        process_error(
            migration_instance, f"Migration precheck failed with error:{error}", status=MigrationStatus.FailedAtStartup
        )
        return False

    ok, error = run_migration_healthcheck(migration_instance)
    if not ok:
        process_error(
            migration_instance,
            f"Migration healthcheck failed with error:{error}",
            status=MigrationStatus.FailedAtStartup,
        )
        return False

    mark_async_migration_as_running(migration_instance)

    return run_async_migration_operations(migration_name, migration_instance)


def run_async_migration_operations(migration_name: str, migration_instance: Optional[AsyncMigration] = None) -> bool:
    while True:
        run_next, success = run_async_migration_next_op(migration_name, migration_instance)
        if not run_next:
            return success


def run_async_migration_next_op(migration_name: str, migration_instance: Optional[AsyncMigration] = None):
    """
    Runs the next operation specified by the currently running migration
    We run the next operation of the migration which needs attention

    Returns (run_next, success)
    Terminology:
    - migration_instance: The migration object as stored in the DB
    - migration_definition: The actual migration class outlining the operations (e.g. async_migrations/examples/example.py)
    """

    if not migration_instance:
        try:
            migration_instance = AsyncMigration.objects.get(name=migration_name, status=MigrationStatus.Running)
        except AsyncMigration.DoesNotExist:
            return (False, False)
    else:
        migration_instance.refresh_from_db()

    assert migration_instance is not None

    migration_definition = get_async_migration_definition(migration_name)
    if migration_instance.current_operation_index > len(migration_definition.operations) - 1:
        complete_migration(migration_instance)
        return (False, True)

    error = None
    current_query_id = str(UUIDT())

    try:
        op = migration_definition.operations[migration_instance.current_operation_index]

        execute_op(op, current_query_id)
        update_async_migration(
            migration_instance=migration_instance,
            current_query_id=current_query_id,
            current_operation_index=migration_instance.current_operation_index + 1,
        )

    except Exception as e:
        error = f"Exception was thrown while running operation {migration_instance.current_operation_index} : {str(e)}"
        process_error(migration_instance, error, alert=True)

    if error:
        return (False, False)

    update_migration_progress(migration_instance)
    return (True, False)


def run_migration_healthcheck(migration_instance: AsyncMigration):
    return get_async_migration_definition(migration_instance.name).healthcheck()


def run_migration_precheck(migration_instance: AsyncMigration):
    return get_async_migration_definition(migration_instance.name).precheck()


def update_migration_progress(migration_instance: AsyncMigration):
    """
    We don't want to interrupt a migration if the progress check fails, hence try without handling exceptions
    Progress is a nice-to-have bit of feedback about how the migration is doing, but not essential
    """

    migration_instance.refresh_from_db()
    try:
        progress = get_async_migration_definition(migration_instance.name).progress(migration_instance)
        update_async_migration(migration_instance=migration_instance, progress=progress)
    except:
        pass


def attempt_migration_rollback(migration_instance: AsyncMigration):
    """
    Cycle through the operations in reverse order starting from the last completed op and run
    the specified rollback statements.
    """
    migration_instance.refresh_from_db()
    ops = get_async_migration_definition(migration_instance.name).operations
    # if the migration was completed the index is set 1 after, normally we should try rollback for current op
    current_index = min(migration_instance.current_operation_index, len(ops) - 1)
    for op_index in range(current_index, -1, -1):
        try:
            op = ops[op_index]
            execute_op(op, str(UUIDT()), rollback=True)
        except Exception as e:
            error = f"At operation {op_index} rollback failed with error:{str(e)}"
            process_error(
                migration_instance=migration_instance,
                error=error,
                rollback=False,
                alert=True,
                current_operation_index=op_index,
            )

            return

    update_async_migration(
        migration_instance=migration_instance, status=MigrationStatus.RolledBack, progress=0, current_operation_index=0
    )


def is_posthog_version_compatible(posthog_min_version, posthog_max_version):
    return POSTHOG_VERSION in SimpleSpec(f">={posthog_min_version},<={posthog_max_version}")


def run_next_migration(candidate: str):
    migration_instance = AsyncMigration.objects.get(name=candidate)
    migration_in_range = is_posthog_version_compatible(
        migration_instance.posthog_min_version, migration_instance.posthog_max_version
    )

    dependency_ok, _ = is_migration_dependency_fulfilled(candidate)

    if dependency_ok and migration_in_range and migration_instance.status == MigrationStatus.NotStarted:
        trigger_migration(migration_instance)


def is_migration_dependency_fulfilled(migration_name: str) -> Tuple[bool, str]:
    dependency = get_async_migration_dependency(migration_name)

    dependency_ok: bool = (
        not dependency or AsyncMigration.objects.get(name=dependency).status == MigrationStatus.CompletedSuccessfully
    )
    error = f"Could not trigger migration because it depends on {dependency}" if not dependency_ok else ""
    return dependency_ok, error


def check_service_version_requirements(
    service_version_requirements: List[ServiceVersionRequirement],
) -> Tuple[bool, str]:
    for service_version_requirement in service_version_requirements:
        in_range, version = service_version_requirement.is_service_in_accepted_version()
        if not in_range:
            return (
                False,
                f"Service {service_version_requirement.service} is in version {version}. Expected range: {str(service_version_requirement.supported_version)}.",
            )

    return True, ""
