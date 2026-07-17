from django.db import models

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.conversations.backend.models.constants import ImportJobStatus


class PlainImportJob(TeamScopedRootMixin, UUIDModel):
    Status = ImportJobStatus

    # db_constraint=False: a real FK constraint would take SHARE ROW EXCLUSIVE on the
    # hot posthog_team table on CreateModel. App-level enforcement is enough here.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    status = models.CharField(max_length=32, choices=ImportJobStatus, default=ImportJobStatus.PENDING)

    total_tickets = models.BigIntegerField(default=0)
    processed_tickets = models.BigIntegerField(default=0)
    imported_tickets = models.BigIntegerField(default=0)
    skipped_tickets = models.BigIntegerField(default=0)
    failed_tickets = models.BigIntegerField(default=0)

    export_cursor = models.TextField(null=True, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    workflow_id = models.CharField(max_length=400, null=True, blank=True)
    workflow_run_id = models.CharField(max_length=400, null=True, blank=True)
    latest_error = models.TextField(null=True, blank=True)

    # Encrypted: api_key, region ("uk" | "us")
    job_inputs = EncryptedJSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_plain_import_job"
        indexes = [
            models.Index(fields=["team", "-created_at"], name="posthog_con_pl_import_team_idx"),
            models.Index(fields=["team", "status"], name="posthog_con_pl_import_stat_idx"),
        ]
