from django.db import models

from posthog.models.utils import UUIDModel
from posthog.models.team import Team

from posthog.helpers.encrypted_fields import EncryptedJSONStringField


class BatchImport(UUIDModel):
    class Outcome(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILURE = "failure", "Failure"

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
    outcome = models.TextField(choices=Outcome.choices, null=True, blank=True)

    # A json object describing the state the job is in. I'm being deliberately vague here,
    # to let me be flexible in the worker code without needing a migration.
    state = models.JSONField(null=True, blank=True)
    # A json object describing the configuration of the job. As above
    import_config = models.JSONField()
    # The secrets needed to do this job - api keys etc. Referenced by the import_config
    secrets = EncryptedJSONStringField()
