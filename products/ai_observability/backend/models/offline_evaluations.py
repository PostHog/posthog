from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import F, Func, Q, Value
from django.db.models.lookups import Exact
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class PayloadState(models.TextChoices):
    NOT_PROVIDED = "not_provided", "Not provided"
    AVAILABLE = "available", "Available"
    EXPIRED = "expired", "Expired"


class OfflineExperiment(TeamScopedRootMixin):
    class Status(models.TextChoices):
        UPLOADING = "uploading", "Uploading"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class RunSource(models.TextChoices):
        CI = "ci", "CI"
        LOCAL = "local", "Local"
        SCHEDULED = "scheduled", "Scheduled"

    id = models.UUIDField(primary_key=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    name = models.CharField(max_length=400)
    run_source = models.CharField(max_length=16, choices=RunSource.choices, null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UPLOADING)
    started_at = models.DateTimeField()
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    finished_at = models.DateTimeField(null=True, blank=True)
    expected_item_count = models.PositiveBigIntegerField(null=True, blank=True)
    expected_result_count = models.PositiveBigIntegerField(null=True, blank=True)
    submission_fingerprint = models.CharField(max_length=64)
    suite_key = models.CharField(max_length=255, null=True, blank=True)
    dataset_source = models.CharField(max_length=255, null=True, blank=True)
    dataset_identifier = models.CharField(max_length=255, null=True, blank=True)
    dataset_revision_identifier = models.CharField(max_length=255, null=True, blank=True)
    # Composite foreign keys in migrations enforce these resource links and their project ownership.
    dataset_revision = models.ForeignKey(
        "ai_observability.DatasetRevision",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_constraint=False,
    )
    application_version = models.CharField(max_length=255, null=True, blank=True)
    model_version = models.CharField(max_length=255, null=True, blank=True)
    prompt_version = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "llm_analytics_offlineexperiment"
        constraints = [
            models.UniqueConstraint(fields=["id", "team"], name="aio_offline_exp_owner_uniq"),
            models.CheckConstraint(
                condition=(
                    Q(status="uploading", finished_at__isnull=True)
                    | Q(status__in=["completed", "failed"], finished_at__isnull=False)
                ),
                name="aio_offline_exp_status_check",
            ),
            models.CheckConstraint(
                condition=Q(finished_at__isnull=True) | Q(finished_at__gte=F("created_at")),
                name="aio_offline_exp_finished_check",
            ),
            models.CheckConstraint(
                condition=Q(run_source__isnull=True) | Q(run_source__in=["ci", "local", "scheduled"]),
                name="aio_offline_exp_source_check",
            ),
            models.CheckConstraint(
                condition=Q(submission_fingerprint__regex=r"^[0-9a-f]{64}$"),
                name="aio_offline_exp_hash_check",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "-started_at", "id"], name="aio_offline_exp_list_idx"),
        ]


class OfflinePayloadOwner(TeamScopedRootMixin):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    accepted_at = models.DateTimeField(default=timezone.now, editable=False)
    payload_state = models.CharField(max_length=16, choices=PayloadState.choices, default=PayloadState.NOT_PROVIDED)
    payload_expires_at = models.DateTimeField(null=True, blank=True)
    submission_fingerprint = models.CharField(max_length=64)

    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(payload_state="not_provided", payload_expires_at__isnull=True)
                    | Q(
                        payload_state__in=["available", "expired"],
                        payload_expires_at__isnull=False,
                        payload_expires_at__gt=F("accepted_at"),
                    )
                ),
                name="%(class)s_payload_check",
            ),
            models.CheckConstraint(
                condition=Q(submission_fingerprint__regex=r"^[0-9a-f]{64}$"),
                name="%(class)s_hash_check",
            ),
        ]


class OfflineExperimentItem(OfflinePayloadOwner):
    id = models.UUIDField(primary_key=True)
    experiment = models.ForeignKey(OfflineExperiment, on_delete=models.CASCADE, related_name="items", db_index=False)
    case_key = models.CharField(max_length=255, null=True, blank=True)
    trial = models.CharField(max_length=255, null=True, blank=True)
    dataset_item_identifier = models.CharField(max_length=255, null=True, blank=True)
    dataset_item_version_identifier = models.CharField(max_length=255, null=True, blank=True)
    dataset_item_version = models.ForeignKey(
        "ai_observability.DatasetItemVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_constraint=False,
    )
    application_trace_id = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "llm_analytics_offlineexperimentitem"
        constraints = [
            *OfflinePayloadOwner.Meta.constraints,
            models.UniqueConstraint(fields=["id", "team"], name="aio_offline_item_owner_uniq"),
        ]
        indexes = [
            models.Index(fields=["experiment", "id"], name="aio_offline_item_exp_idx"),
        ]


class OfflineEvaluationResult(OfflinePayloadOwner, UUIDModel):
    class Status(models.TextChoices):
        OK = "ok", "OK"
        ERROR = "error", "Error"
        SKIPPED = "skipped", "Skipped"
        NOT_APPLICABLE = "not_applicable", "Not applicable"

    item = models.ForeignKey(OfflineExperimentItem, on_delete=models.CASCADE, related_name="results", db_index=False)
    # The definition lets composite foreign keys enforce both version membership and project ownership.
    scorer_definition = models.ForeignKey(
        "ai_observability.ScoreDefinition", on_delete=models.RESTRICT, related_name="+", db_constraint=False
    )
    # RESTRICT preserves scorer history while permitting the team's complete deletion cascade.
    scorer_version = models.ForeignKey(
        "ai_observability.ScoreDefinitionVersion",
        on_delete=models.RESTRICT,
        related_name="offline_results",
        db_constraint=False,
    )
    status = models.CharField(max_length=16, choices=Status.choices)
    numeric_value = models.FloatField(null=True, blank=True)
    boolean_value = models.BooleanField(null=True, blank=True)
    categorical_values = ArrayField(models.CharField(max_length=128), null=True, blank=True)
    error_code = models.CharField(max_length=128, null=True, blank=True)
    evaluator_trace_id = models.CharField(max_length=255, null=True, blank=True)
    evaluated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "llm_analytics_offlineevaluationresult"
        constraints = [
            *OfflinePayloadOwner.Meta.constraints,
            models.UniqueConstraint(fields=["id", "team"], name="aio_offline_result_owner_uniq"),
            models.UniqueConstraint(fields=["item", "scorer_version"], name="aio_offline_result_identity"),
            models.CheckConstraint(
                condition=(
                    Q(status="ok")
                    & (
                        Q(numeric_value__isnull=False, boolean_value__isnull=True, categorical_values__isnull=True)
                        | Q(numeric_value__isnull=True, boolean_value__isnull=False, categorical_values__isnull=True)
                        | Q(numeric_value__isnull=True, boolean_value__isnull=True, categorical_values__isnull=False)
                    )
                    | Q(
                        status__in=["error", "skipped", "not_applicable"],
                        numeric_value__isnull=True,
                        boolean_value__isnull=True,
                        categorical_values__isnull=True,
                    )
                ),
                name="aio_offline_result_value_check",
            ),
            models.CheckConstraint(
                condition=(
                    Q(numeric_value__isnull=True) | Q(numeric_value__gt=float("-inf"), numeric_value__lt=float("inf"))
                ),
                name="aio_offline_result_finite_check",
            ),
            models.CheckConstraint(
                condition=Q(categorical_values__isnull=True) | Q(categorical_values__len__gt=0),
                name="aio_offline_result_cat_check",
            ),
            models.CheckConstraint(
                condition=Q(error_code__isnull=True) | Q(status="error"),
                name="aio_offline_result_error_check",
            ),
        ]
        indexes = [
            models.Index(
                fields=["team", "scorer_version", "-accepted_at", "id"], name="aio_offline_result_history_idx"
            ),
        ]


class OfflinePayload(TeamScopedRootMixin):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    # An object preserves omitted properties separately from explicitly supplied JSON nulls.
    data = models.JSONField()

    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(
                condition=Exact(
                    Func(F("data"), function="jsonb_typeof", output_field=models.CharField()), Value("object")
                ),
                name="%(class)s_object_check",
            ),
        ]


class OfflineExperimentItemPayload(OfflinePayload):
    item = models.OneToOneField(
        OfflineExperimentItem, on_delete=models.CASCADE, primary_key=True, related_name="payload"
    )

    class Meta:
        db_table = "llm_analytics_offlineexperimentitempayload"
        constraints = OfflinePayload.Meta.constraints


class OfflineEvaluationResultPayload(OfflinePayload):
    result = models.OneToOneField(
        OfflineEvaluationResult, on_delete=models.CASCADE, primary_key=True, related_name="payload"
    )

    class Meta:
        db_table = "llm_analytics_offlineevaluationresultpayload"
        constraints = OfflinePayload.Meta.constraints
