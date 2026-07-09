from django.db import models, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

import structlog

# DRF's ValidationError (not Django's) so save() raise sites surface as 400s via the DRF exception
# handler — Django's variant falls through to the unhandled-exception path and returns a 500.
from rest_framework.exceptions import ValidationError

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import UUIDTModel

from .evaluation_configs import (
    EVALUATION_CONFIG_MODELS,
    EvaluationType,
    OutputType,
    evaluation_configs_allow_empty,
    evaluation_uses_model_configuration,
    validate_evaluation_configs,
    validate_target_config,
)

logger = structlog.get_logger(__name__)


class EvaluationStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    ERROR = "error", "Error"


class EvaluationStatusReason(models.TextChoices):
    PROVIDER_KEY_REQUIRED = "provider_key_required", "No provider API key configured"
    # Trial reasons — retained while mid-trial teams are grandfathered; removed once the trial is fully deprecated.
    TRIAL_LIMIT_REACHED = "trial_limit_reached", "Trial evaluation limit reached"
    MODEL_NOT_ALLOWED = "model_not_allowed", "Model not available on the trial plan"
    PROVIDER_KEY_DELETED = "provider_key_deleted", "Provider API key was deleted"
    NO_DEFAULT_MODEL = "no_default_model", "No default model available for the selected provider"
    PROVIDER_KEY_INVALID = "provider_key_invalid", "Provider API key is invalid"
    PROVIDER_KEY_PERMISSION_DENIED = "provider_key_permission_denied", "Provider API key lacks model access"
    PROVIDER_KEY_QUOTA_EXCEEDED = "provider_key_quota_exceeded", "Provider API key quota exceeded"
    PROVIDER_KEY_RATE_LIMITED = "provider_key_rate_limited", "Provider API key is rate limited"
    MODEL_NOT_FOUND = "model_not_found", "Model not found"
    HOG_ERROR = "hog_error", "Hog evaluation code failed"


class EvaluationQuerySet(models.QuerySet):
    def using_provider_keys(self) -> "EvaluationQuerySet":
        return self.filter(evaluation_type=EvaluationType.LLM_JUDGE)


class EvaluationTarget(models.TextChoices):
    GENERATION = "generation", "Generation"
    TRACE = "trace", "Trace"


class Evaluation(ModelActivityMixin, UUIDTModel):
    class Meta:
        db_table = "llm_analytics_evaluation"
        ordering = ["-created_at", "id"]
        indexes = [
            models.Index(fields=["team", "-created_at", "id"]),
            models.Index(fields=["team", "enabled"]),
            models.Index(fields=["model_configuration"], name="llm_analyti_model_c_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                name="model_config_only_on_llm_judge",
                condition=models.Q(model_configuration__isnull=True)
                | models.Q(evaluation_type=EvaluationType.LLM_JUDGE),
            ),
        ]

    objects = EvaluationQuerySet.as_manager()

    # Core fields
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")

    # Lifecycle state. `status` is authoritative; `enabled` is a boolean projection kept in sync by save() for
    # backwards compatibility with existing API / DB callers. When status is ERROR, status_reason must be set.
    enabled = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=EvaluationStatus, default=EvaluationStatus.PAUSED)
    status_reason = models.CharField(max_length=50, choices=EvaluationStatusReason, null=True, blank=True)
    status_reason_detail = models.TextField(null=True, blank=True)

    evaluation_type = models.CharField(max_length=50, choices=EvaluationType)
    evaluation_config = models.JSONField(default=dict)
    output_type = models.CharField(max_length=50, choices=OutputType)
    output_config = models.JSONField(default=dict)

    conditions = models.JSONField(default=list)

    # What unit the evaluation runs on: a single $ai_generation event, or the whole trace
    # (debounced and pulled from ClickHouse after an aggregation window).
    target = models.CharField(
        max_length=20,
        choices=EvaluationTarget,
        default=EvaluationTarget.GENERATION,
        db_default=EvaluationTarget.GENERATION,
    )
    # Target-specific settings, keyed off `target` (parallel to evaluation_config/output_config).
    # Trace targets carry {window_seconds}; generation targets carry nothing.
    target_config = models.JSONField(default=dict, db_default=models.Value("{}"))

    # Model configuration for the LLM judge
    model_configuration = models.ForeignKey(
        "ai_observability.LLMModelConfiguration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluations",
        db_index=False,
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(default=False)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Snapshot of the fields as last loaded / saved — used by _coerce_status_and_enabled to know which
        # field the caller actually moved when enabled and status disagree.
        self._initial_enabled = self.enabled
        self._initial_status = self.status

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._initial_enabled = instance.enabled
        instance._initial_status = instance.status
        return instance

    def refresh_from_db(self, *args, **kwargs) -> None:
        # Refreshing replaces the in-memory state with DB state — the change-tracking baseline must
        # follow, otherwise a subsequent caller-side edit would be compared against stale initials and
        # the coerce step could misinterpret which field moved.
        super().refresh_from_db(*args, **kwargs)
        self._initial_enabled = self.enabled
        self._initial_status = self.status

    def __str__(self):
        return self.name

    def _coerce_status_and_enabled(self) -> None:
        """Reconcile status with enabled at save time.

        New records: derive status from enabled unless the caller explicitly set status (e.g. ERROR + reason).
        Existing records: whichever field actually changed since load drives the other. This lets existing
        callers keep PATCHing `enabled` without knowing about status, while system transitions that write
        `status` directly take effect even when `enabled` is stale in memory.

        Post-reconciliation invariants are always enforced:
            - ACTIVE  → enabled=True,  status_reason/detail=None
            - PAUSED  → enabled=False, status_reason/detail=None
            - ERROR   → enabled=False, status_reason required (raises otherwise)
        """
        # UUIDTModel assigns pk in __init__, so we can't use `self.pk is None` to detect new rows.
        is_new = self._state.adding
        if is_new:
            if self.status == EvaluationStatus.PAUSED and self.enabled:
                self.status = EvaluationStatus.ACTIVE
            elif self.status == EvaluationStatus.ACTIVE and not self.enabled:
                self.status = EvaluationStatus.PAUSED
        else:
            enabled_changed = self.enabled != self._initial_enabled
            status_changed = self.status != self._initial_status
            if status_changed and not enabled_changed:
                self.enabled = self.status == EvaluationStatus.ACTIVE
            elif enabled_changed and not status_changed:
                self.status = EvaluationStatus.ACTIVE if self.enabled else EvaluationStatus.PAUSED

        if self.status == EvaluationStatus.ACTIVE:
            self.enabled = True
            self.status_reason = None
            self.status_reason_detail = None
        elif self.status == EvaluationStatus.PAUSED:
            self.enabled = False
            self.status_reason = None
            self.status_reason_detail = None
        elif self.status == EvaluationStatus.ERROR:
            self.enabled = False
            if not self.status_reason:
                raise ValidationError({"status_reason": "status_reason is required when status is ERROR"})

    def set_status(
        self,
        status: "EvaluationStatus | str",
        reason: "EvaluationStatusReason | str | None" = None,
        reason_detail: str | None = None,
    ) -> None:
        """Transition helper. Prefer this (or .save()) over .update() so invariants stay enforced.

        Callers using QuerySet.update() bypass save() — they must write the status fields together.
        """
        self.status = EvaluationStatus(status)
        self.status_reason = EvaluationStatusReason(reason) if reason else None
        self.status_reason_detail = reason_detail
        self.save(update_fields=["status", "status_reason", "status_reason_detail", "enabled", "updated_at"])

    def save(self, *args, **kwargs):
        from posthog.cdp.filters import compile_filters_bytecode

        from ..hog import compile_ai_observability_hog  # noqa: PLC0415 - keeps Hog compiler off model import path

        # Coerce status and enabled into a consistent pair. status is authoritative, but we accept writes to
        # either field — typically `enabled` from user PATCHes, `status` from system transitions.
        self._coerce_status_and_enabled()

        if not evaluation_uses_model_configuration(self.evaluation_type) and self.model_configuration_id:
            raise ValidationError({"model_configuration": "This evaluation type does not use model configuration."})

        if (self.evaluation_type, self.output_type) not in EVALUATION_CONFIG_MODELS:
            raise ValidationError(f"Unsupported combination: {self.evaluation_type} + {self.output_type}")

        # Validate configs when callers provide them, or when the selected config models can supply every default.
        if (
            evaluation_configs_allow_empty(self.evaluation_type, self.output_type)
            or self.evaluation_config
            or self.output_config
        ):
            try:
                self.evaluation_config, self.output_config = validate_evaluation_configs(
                    self.evaluation_type, self.output_type, self.evaluation_config, self.output_config
                )
            except ValueError as e:
                raise ValidationError(str(e))

        # Validate target config (defaults the trace window when absent, strips it for generation).
        try:
            self.target_config = validate_target_config(self.target, self.target_config)
        except ValueError as e:
            raise ValidationError({"target_config": str(e)})

        # Compile Hog source to bytecode
        if self.evaluation_type == EvaluationType.HOG and self.evaluation_config.get("source"):
            try:
                bytecode = compile_ai_observability_hog(self.evaluation_config["source"], "destination")
                self.evaluation_config["bytecode"] = bytecode
            except Exception as e:
                raise ValidationError({"evaluation_config": f"Failed to compile Hog code: {e}"})

        # Compile bytecode for each condition
        compiled_conditions = []
        for condition in self.conditions:
            compiled_condition = {**condition}
            filters = {"properties": condition.get("properties", [])}
            compiled = compile_filters_bytecode(filters, self.team)
            compiled_condition["bytecode"] = compiled.get("bytecode")
            compiled_condition["bytecode_error"] = compiled.get("bytecode_error")
            compiled_conditions.append(compiled_condition)

        self.conditions = compiled_conditions
        result = super().save(*args, **kwargs)
        # Refresh the baseline so the next save cycle compares against the post-save state.
        self._initial_enabled = self.enabled
        self._initial_status = self.status
        return result


@receiver(post_save, sender=Evaluation)
def evaluation_saved(sender, instance, created, **kwargs):
    from posthog.plugins.plugin_server_api import reload_evaluations_on_workers

    from .evaluation_reports import EvaluationReport

    if instance.deleted:
        EvaluationReport.objects.filter(evaluation_id=instance.id, deleted=False).update(deleted=True, enabled=False)

    # Defer publishing to workers until the surrounding transaction commits — otherwise
    # workers can fire before the row is visible, especially now that perform_create wraps
    # the save + EvaluationReport create in transaction.atomic(). In auto-commit mode
    # on_commit fires synchronously, preserving prior behavior.
    team_id = instance.team_id
    evaluation_id = str(instance.id)
    transaction.on_commit(lambda: reload_evaluations_on_workers(team_id=team_id, evaluation_ids=[evaluation_id]))
