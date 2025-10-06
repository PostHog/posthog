from celery import shared_task, states
from celery.result import AsyncResult

from posthog.async_migrations.runner import (
    run_async_migration_operations,
    run_migration_healthcheck,
    start_async_migration,
    update_migration_progress,
)
from posthog.async_migrations.utils import force_stop_migration, process_error, trigger_migration
from posthog.models.instance_setting import get_instance_setting


# we're hijacking an entire worker to do this - consider:
# 1. spawning a thread within the worker
# 2. suggesting users scale celery when running async migrations
# 3. ...
@shared_task(track_started=True, ignore_result=False, max_retries=0)
def run_async_migration(migration_name: str, fresh_start: bool = True) -> None:
    if fresh_start:
        start_async_migration(migration_name)
        return

    # Resumable operations
    run_async_migration_operations(migration_name)


# This task:
# 1. Checks if the worker crashed and handle the affected migration appropriately
# 2. Does a periodic healthcheck to make sure it's safe to continue running the migration
# 3. Updates migration progress
def check_async_migration_health() -> None:
    from posthog.celery import app
    from posthog.models.async_migration import AsyncMigration, MigrationStatus

    try:
        migration_instance: AsyncMigration = AsyncMigration.objects.get(status=MigrationStatus.Running)
    except AsyncMigration.DoesNotExist:
        return

    migration_task_celery_state = AsyncResult(migration_instance.celery_task_id).state

    # we only care about "supposedly running" tasks here
    # failures and successes are handled elsewhere
    # pending means we haven't picked up the task yet
    # retry is not possible as max_retries == 0
    if migration_task_celery_state not in (
        states.STARTED,
        states.PENDING,
        states.FAILURE,
    ):
        return

    inspector = app.control.inspect()
    active_tasks_per_node = inspector.active()

    active_task_ids = []

    if active_tasks_per_node:
        for _, tasks in active_tasks_per_node.items():
            active_task_ids += [task["id"] for task in tasks]

    # the worker crashed - this is how we find out and process the error
    if migration_instance.celery_task_id not in active_task_ids:
        if get_instance_setting("ASYNC_MIGRATIONS_AUTO_CONTINUE"):
            trigger_migration(migration_instance, fresh_start=False)
        else:
            process_error(migration_instance, "Celery worker crashed while running migration.")
        return

    ok, error = run_migration_healthcheck(migration_instance)

    if not ok:
        force_stop_migration(migration_instance, f"Healthcheck failed with error: {error}")
        return

    update_migration_progress(migration_instance)
