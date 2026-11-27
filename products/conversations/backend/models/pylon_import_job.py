from django.db import models

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from .import_job_base import ImportJobLifecycleFields, ImportJobStatus


class PylonImportJob(TeamScopedRootMixin, UUIDModel, ImportJobLifecycleFields):
    Status = ImportJobStatus

    class Region(models.TextChoices):
        US = "us", "United States"
        EU = "eu", "Europe"

    # db_constraint=False: a real FK constraint would take SHARE ROW EXCLUSIVE on the
    # hot posthog_team table on CreateModel. App-level enforcement is enough here.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    status = models.CharField(max_length=32, choices=Status, default=Status.PENDING)

    total_issues = models.BigIntegerField(default=0)
    processed_issues = models.BigIntegerField(default=0)
    imported_issues = models.BigIntegerField(default=0)
    skipped_issues = models.BigIntegerField(default=0)
    failed_issues = models.BigIntegerField(default=0)

    # Encrypted: region, api_token
    job_inputs = EncryptedJSONField(null=True, blank=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_pylon_import_job"
        indexes = [
            models.Index(fields=["team", "-created_at"], name="posthog_con_py_import_team_idx"),
            models.Index(fields=["team", "status"], name="posthog_con_py_import_stat_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team"],
                condition=models.Q(status__in=["pending", "running"]),
                name="posthog_con_py_import_one_active",
            ),
        ]
