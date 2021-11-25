from django.db import models


# an enum, essentially
class MigrationStatus:
    NotStarted = 0
    Running = 1
    CompletedSuccessfully = 2
    Errored = 3
    RolledBack = 4


class SpecialMigration(models.Model):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["name"], name="unique name",)]

    id: models.BigAutoField = models.BigAutoField(primary_key=True)
    name: models.CharField = models.CharField(max_length=400, null=False, blank=False)
    progress: models.IntegerField = models.IntegerField(null=False, blank=False, default=0)
    status: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(
        null=False, blank=False, default=MigrationStatus.NotStarted
    )

    current_operation_index: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(
        null=False, blank=False, default=0
    )
    current_query_id: models.CharField = models.CharField(max_length=400, null=False, blank=False, default="")
    celery_task_id: models.CharField = models.CharField(max_length=400, null=False, blank=False, default="")

    started_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)

    # Can finish with status 'CompletedSuccessfully', 'Errored', or 'RolledBack'
    finished_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)

    error: models.TextField = models.TextField(null=True, blank=True)


def get_all_completed_special_migrations():
    return SpecialMigration.objects.filter(status=MigrationStatus.CompletedSuccessfully)


def get_all_running_special_migrations():
    return SpecialMigration.objects.filter(status=MigrationStatus.Running)
