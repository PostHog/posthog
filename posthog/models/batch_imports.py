from django.db import models

from posthog.models.utils import UUIDModel
from posthog.models.team import Team

from posthog.helpers.encrypted_fields import EncryptedJSONStringField


class BatchImport(UUIDModel):
    class Status(models.TextChoices):
        COMPLETED = "completed", "Completed"  # Completed successfully
        FAILED = "failed", "Failed"  # Failed, and should not be retried
        PAUSED = "paused", "Paused"  # Paused, awaiting a manual unpause after some fixing action
        RUNNING = "running", "Running"  # Created or running, but not yet finished

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Workers pick up a lease for a job, run a batch of it, then renew their lease, in a loop,
    # until the job is done.
    lease_id = models.TextField(null=True, blank=True)
    leased_until = models.DateTimeField(null=True, blank=True)

    # Since the state/config of the job is opaque to the DB, we store the outcome at the
    # DB level, to prevent other workers from picking up a finished job. Any error messages
    # etc are store in the state.
    status = models.TextField(choices=Status.choices, default=Status.RUNNING)
    # If we're e.g. paused, we can put some user-facing message here
    status_message = models.TextField(null=True, blank=True)

    # A json object describing the state the job is in. I'm being deliberately vague here,
    # to let me be flexible in the worker code without needing a migration.
    state = models.JSONField(null=True, blank=True)
    # A json object describing the configuration of the job. As above
    import_config = models.JSONField()
    # The secrets needed to do this job - api keys etc. Referenced by the import_config
    secrets = EncryptedJSONStringField()


# Create a test job, configured to read from the workers local filesystem and
# write to either stdout in json format
def create_test_job(team: Team, path: str) -> BatchImport:
    source_config = {
        "type": "folder",
        "path": path,
    }

    data_format = {"type": "jsonlines", "skip_blanks": False, "content": {"type": "mixpanel"}}

    sink_config = {"type": "stdout", "as_json": True}

    import_config = {"source": source_config, "data_format": data_format, "sink": sink_config}

    secrets = {"test": "test"}

    return BatchImport.objects.create(
        team=team,
        import_config=import_config,
        secrets=secrets,
    )
