from django.db import models


# an enum, essentially
class MigrationStatus:
    NotStarted = 0
    Running = 1
    CompletedSuccessfully = 2
    Errored = 3
    RolledBack = 4
    Starting = 5  # only relevant for the UI
    FailedAtStartup = 6


class AsyncMigrationError(models.Model):
    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    description = models.TextField(null=False, blank=False)
    async_migration = models.ForeignKey("AsyncMigration", on_delete=models.CASCADE)


class AsyncMigration(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=50, null=False, blank=False)
    description = models.CharField(max_length=400, null=True, blank=True)
    progress = models.PositiveSmallIntegerField(null=False, blank=False, default=0)
    status = models.PositiveSmallIntegerField(null=False, blank=False, default=MigrationStatus.NotStarted)

    current_operation_index = models.PositiveSmallIntegerField(null=False, blank=False, default=0)
    current_query_id = models.CharField(max_length=100, null=False, blank=False, default="")
    celery_task_id = models.CharField(max_length=100, null=False, blank=False, default="")

    started_at = models.DateTimeField(null=True, blank=True)

    # Can finish with status 'CompletedSuccessfully', 'Errored', or 'RolledBack'
    finished_at = models.DateTimeField(null=True, blank=True)

    posthog_min_version = models.CharField(max_length=20, null=True, blank=True)
    posthog_max_version = models.CharField(max_length=20, null=True, blank=True)

    parameters = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["name"], name="unique name")]

    def get_name_with_requirements(self) -> str:
        return (
            f"{self.name} - must be ran on PostHog version {self.posthog_min_version} up to {self.posthog_max_version}"
        )


def get_all_completed_async_migrations():
    return AsyncMigration.objects.filter(status=MigrationStatus.CompletedSuccessfully)


def get_all_running_async_migrations():
    return AsyncMigration.objects.filter(status=MigrationStatus.Running)


def get_async_migrations_by_status(target_statuses: list[int]):
    return AsyncMigration.objects.filter(status__in=target_statuses)


# allow for splitting code paths
def is_async_migration_complete(migration_name: str) -> bool:
    migration_instance = AsyncMigration.objects.filter(
        name=migration_name, status=MigrationStatus.CompletedSuccessfully
    ).first()
    return migration_instance is not None
