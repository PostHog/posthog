from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class DataQualityQuestionExecution(TeamScopedRootMixin, UUIDModel):
    created_at = models.DateTimeField(auto_now_add=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    suite_run = models.ForeignKey("data_quality.DataQualitySuiteRun", on_delete=models.CASCADE)
    definition_id = models.UUIDField()
    quality_check = models.ForeignKey("data_quality.DataQualityCheck", on_delete=models.SET_NULL, null=True)
    check_run = models.OneToOneField(
        "data_quality.DataQualityCheckRun", on_delete=models.SET_NULL, null=True, related_name="question_execution"
    )
    principal = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, db_constraint=False, related_name="+"
    )
    subject_uuid = models.UUIDField()
    subject_name = models.CharField(max_length=400)
    column_name = models.CharField(max_length=400, blank=True)
    check_config = models.JSONField()
    check_fingerprint = models.CharField(max_length=64)
    model_id = models.CharField(max_length=400)
    model_revision = models.CharField(max_length=400)
    evaluator_version = models.PositiveIntegerField()
    manifest_key = models.CharField(max_length=400, blank=True)
    deadline = models.DateTimeField()
    total_chunk_count = models.PositiveIntegerField(default=0)
    examined_row_count = models.BigIntegerField(default=0)
    unique_input_count = models.PositiveIntegerField(default=0)
    reserved_inference_inputs = models.PositiveIntegerField(default=0)
    result = models.JSONField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["suite_run", "definition_id"], name="dq_question_suite_check")]


class DataQualityQuestionCheckpoint(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    execution = models.ForeignKey("data_quality.DataQualityQuestionExecution", on_delete=models.CASCADE)
    chunk_index = models.PositiveIntegerField()
    examined_row_count = models.BigIntegerField()
    failed_row_count = models.BigIntegerField()
    unique_input_count = models.PositiveIntegerField()
    reused_decision_count = models.PositiveIntegerField()
    new_decision_count = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["execution", "chunk_index"], name="dq_question_run_chunk")]


class DataQualityQuestionSnapshot(TeamScopedRootMixin, UUIDModel):
    created_at = models.DateTimeField(auto_now_add=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+")
    # Retention owns deletion even after the execution or its suite has been removed.
    execution = models.ForeignKey("data_quality.DataQualityQuestionExecution", on_delete=models.SET_NULL, null=True)
    prefix = models.CharField(max_length=400, unique=True)
    expires_at = models.DateTimeField(db_index=True)
