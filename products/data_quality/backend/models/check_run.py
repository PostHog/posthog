from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from ..facade.enums import CheckRunStatus, CheckSeverity, SubjectType, SuiteRunStatus, SuiteRunTrigger


class DataQualitySuiteRun(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """One batch of check executions, and the handle an API caller polls for a report.

    A suite is scoped to whatever the trigger asked for -- a single subject, an explicit set of
    checks, or every check on the models a DAG run just materialized -- so the optional subject
    columns are a convenience for the common single-subject case, not the run's identity.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )

    trigger = models.CharField(
        max_length=32,
        choices=[(t.value, t.value) for t in SuiteRunTrigger],
        help_text="What started this run: manual, materialization, or source_sync.",
    )
    status = models.CharField(
        max_length=16,
        choices=[(s.value, s.value) for s in SuiteRunStatus],
        default=SuiteRunStatus.RUNNING,
        help_text="empty means the trigger matched no runnable checks, which is not a failure.",
    )

    subject_type = models.CharField(
        max_length=32,
        choices=[(t.value, t.value) for t in SubjectType],
        blank=True,
        help_text="Set when the run targets exactly one subject.",
    )
    subject_uuid = models.UUIDField(null=True, blank=True, help_text="Set when the run targets exactly one subject.")

    workflow_id = models.CharField(max_length=400, blank=True)
    workflow_run_id = models.CharField(max_length=400, blank=True)
    # Loose reference, not an FK: DataModelingJob is another product's model.
    data_modeling_job_id = models.UUIDField(
        null=True, blank=True, help_text="The materialization job that triggered this run, if any."
    )

    checks_passed = models.IntegerField(default=0)
    checks_failed = models.IntegerField(default=0)
    checks_errored = models.IntegerField(default=0)
    checks_skipped = models.IntegerField(default=0)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, help_text="Why the suite itself failed, as opposed to an individual check.")

    class Meta:
        indexes = [
            models.Index(fields=["team", "-created_at"]),
            models.Index(fields=["team", "subject_type", "subject_uuid"]),
        ]

    def __str__(self) -> str:
        return f"suite run {self.id} ({self.status})"


class DataQualityCheckRun(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """One execution of one check.

    Deliberately stores counts and the compiled query, never failing rows -- warehouse data can be
    sensitive and this table lives in the main Postgres. To see the offending rows, re-run
    ``compiled_query``.

    ``observed_value`` is recorded on passes too, not just failures: the resulting numeric time
    series is what future anomaly-detection check types train on.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    # Named quality_check, never check: Django reserves Model.check() and a field called `check`
    # shadows it (models.E020).
    quality_check = models.ForeignKey(
        "data_quality.DataQualityCheck",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="runs",
        help_text="The definition executed. Nulled rather than cascaded so history outlives hard deletes.",
    )
    suite_run = models.ForeignKey(
        "data_quality.DataQualitySuiteRun",
        on_delete=models.CASCADE,
        related_name="check_runs",
    )

    # Denormalized from the check so history stays readable after the definition changes or goes away.
    subject_type = models.CharField(max_length=32, choices=[(t.value, t.value) for t in SubjectType])
    subject_uuid = models.UUIDField()
    subject_name = models.CharField(max_length=400)
    # No choices, for the same reason as on the check itself: the registry owns the set of types.
    check_type = models.CharField(max_length=32)
    check_fingerprint = models.CharField(max_length=64)
    column_name = models.CharField(max_length=400, blank=True)
    # Null means "recorded before runs snapshotted this", never "same as the check has now": a
    # definition can be edited after the fact, so borrowing the current values would misreport
    # what actually ran.
    check_config = models.JSONField(
        null=True, blank=True, help_text="Canonical config this run executed. Null for runs recorded before snapshots."
    )
    check_severity = models.CharField(
        max_length=16,
        choices=[(s.value, s.value) for s in CheckSeverity],
        null=True,
        blank=True,
        help_text="Severity this run was judged at. Null for runs recorded before snapshots.",
    )

    status = models.CharField(max_length=16, choices=[(s.value, s.value) for s in CheckRunStatus])
    failed_row_count = models.BigIntegerField(
        null=True, blank=True, help_text="Rows violating the assertion. 0 is a pass."
    )
    observed_value = models.FloatField(
        null=True,
        blank=True,
        help_text="The check's headline number (row count, staleness in seconds, ...), kept as a time series.",
    )
    compiled_query = models.TextField(
        blank=True,
        help_text="HogQL selecting the failing rows. Re-run it to see them. Cleared by retention after 30 days.",
    )
    error = models.TextField(blank=True, help_text="Compilation or execution failure, for status=errored.")
    duration_ms = models.IntegerField(null=True, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["quality_check", "-created_at"]),
            models.Index(fields=["team", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.check_type} on {self.subject_name}: {self.status}"
