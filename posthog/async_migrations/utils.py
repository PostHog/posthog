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
from posthog.email import is_email_available
from posthog.models.async_migration import AsyncMigration, AsyncMigrationError, MigrationStatus
from posthog.models.instance_setting import get_instance_setting
from posthog.models.user import User
from posthog.utils import get_machine_id

logger = structlog.get_logger(__name__)


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


def execute_op_clickhouse(sql: str, query_id: str, timeout_seconds: Optional[int] = None, settings=None):
    from posthog.client import sync_execute

    settings = settings if settings else {"max_execution_time": timeout_seconds}

    try:
        sync_execute(f"/* {query_id} */ " + sql, settings=settings)
    except Exception as e:
        raise Exception(f"Failed to execute ClickHouse op: sql={sql},\nquery_id={query_id},\nexception={str(e)}")


def execute_op_postgres(sql: str, query_id: str):
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute(f"/* {query_id} */ " + sql)
    except Exception as e:
        raise Exception(f"Failed to execute postgres op: sql={sql},\nquery_id={query_id},\nexception={str(e)}")


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
