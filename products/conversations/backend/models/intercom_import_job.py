from django.db import models

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class IntercomImportJob(TeamScopedRootMixin, UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class Region(models.TextChoices):
        US = "us", "United States"
        EU = "eu", "Europe"
        AU = "au", "Australia"

    # db_constraint=False: a real FK constraint would take SHARE ROW EXCLUSIVE on the
    # hot posthog_team table on CreateModel. App-level enforcement is enough here.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    status = models.CharField(max_length=32, choices=Status, default=Status.PENDING)

    total_conversations = models.BigIntegerField(default=0)
    processed_conversations = models.BigIntegerField(default=0)
    imported_conversations = models.BigIntegerField(default=0)
    skipped_conversations = models.BigIntegerField(default=0)
    failed_conversations = models.BigIntegerField(default=0)

    export_cursor = models.TextField(null=True, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    workflow_id = models.CharField(max_length=400, null=True, blank=True)
    workflow_run_id = models.CharField(max_length=400, null=True, blank=True)
    latest_error = models.TextField(null=True, blank=True)

    # Encrypted: region, access_token
    job_inputs = EncryptedJSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_intercom_import_job"
        indexes = [
            models.Index(fields=["team", "-created_at"], name="posthog_con_ic_import_team_idx"),
            models.Index(fields=["team", "status"], name="posthog_con_ic_import_stat_idx"),
        ]
