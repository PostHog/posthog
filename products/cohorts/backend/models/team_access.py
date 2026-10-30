from django.db import models


class RealtimeCohortLevel(models.TextChoices):
    OFF = "off", "Off"
    # The pipeline maintains membership for the team, but nothing the team's users see reads it.
    PROCESSING = "processing", "Processing"
    # Processing, plus the realtime surfaces the team's users see.
    SERVING = "serving", "Serving"


class RealtimeCohortAccessPurpose(models.TextChoices):
    PILOT = "pilot", "Pilot"
    LOAD_TEST = "load_test", "Load test"


class RealtimeCohortTeamAccess(models.Model):
    """A team's access to the realtime cohort pipeline, granted on top of `REALTIME_COHORT_TEAM_ALLOWLIST`.

    Staff write it only through the `realtime_cohort_team_access` command. Only Django reads it, so the
    Rust services' env lists must change with it. A missing row means `off`. Never read it through
    `get_or_create_team_extension`, because that creates the row.

    Rows are never deleted: a revoke sets `off`, and a team deletion leaves the row (`DO_NOTHING`).
    So when a team's row appears on one read and is missing on a later one, the later read failed.
    A reader treats that as an error, not as a revoke.
    """

    # db_constraint=False: a real FK constraint would take a SHARE ROW EXCLUSIVE lock on
    # posthog_team (a hot table) while migrating. The column stays int4, which the Rust services decode.
    team = models.OneToOneField(
        "posthog.Team", on_delete=models.DO_NOTHING, primary_key=True, db_constraint=False, related_name="+"
    )
    level = models.CharField(max_length=16, choices=RealtimeCohortLevel.choices)
    purpose = models.CharField(max_length=16, choices=RealtimeCohortAccessPurpose.choices)
    # The row's half of `COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST`: whether a cohort save enqueues a backfill.
    save_triggers_backfill = models.BooleanField(default=False)
    # Set only on a move from off to on, and kept through later level changes.
    processing_since = models.DateTimeField(null=True)
    # Set only on a move to off.
    off_since = models.DateTimeField(null=True)
    changed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cohort_realtime_team_access"
