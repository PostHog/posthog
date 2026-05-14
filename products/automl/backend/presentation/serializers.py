"""DRF serializers for AutoML.

Converts DTOs to/from JSON using DataclassSerializer. Field types are
auto-derived from the frozen dataclasses in ``facade/contracts.py``.
"""

from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    AutoMLModelVersionDTO,
    AutoMLPipelineDTO,
    AutoMLPipelineRunDTO,
    CreatePipelineInput,
    RecordBootstrapOutcomeInput,
    RecordEdaResultInput,
    RecordInferenceOutcomeInput,
    RecordTrainingResultInput,
    UpdatePipelineInput,
    ValidationFinding,
    ValidationReport,
    ValidationSummary,
)


class AutoMLPipelineSerializer(DataclassSerializer):
    """Output shape of an AutoML pipeline."""

    class Meta:
        dataclass = AutoMLPipelineDTO


class CreatePipelineInputSerializer(DataclassSerializer):
    """Request body for ``POST /automl_pipelines/``.

    ``team_id`` and ``created_by_id`` are injected by the view from the
    request scope and aren't part of the DTO.
    """

    class Meta:
        dataclass = CreatePipelineInput


class UpdatePipelineInputSerializer(DataclassSerializer):
    """Request body for ``PATCH /automl_pipelines/{id}/``.

    All fields are optional; ``None`` means leave unchanged. Status
    transitions go through the dedicated start / pause / resume / archive
    actions instead of this endpoint.
    """

    class Meta:
        dataclass = UpdatePipelineInput


class AutoMLModelVersionSerializer(DataclassSerializer):
    """Output shape of one trained model version on a pipeline.

    One row per training run; ``id`` is what propagates onto emitted predictions
    as ``$model_version_id``. ``role`` (champion / challenger / archived) drives
    whether the version serves traffic.
    """

    class Meta:
        dataclass = AutoMLModelVersionDTO


class RecordTrainingResultInputSerializer(DataclassSerializer):
    """Request body for ``POST /automl_pipelines/{id}/model_versions/``.

    Called by the bootstrap / retraining agent when a training run finishes.
    ``role`` defaults to ``challenger`` so a fresh run never auto-displaces the
    existing champion — promotion is a separate explicit step.
    """

    class Meta:
        dataclass = RecordTrainingResultInput


class ValidationFindingSerializer(DataclassSerializer):
    """One finding in a validation report (severity + code + message + details)."""

    class Meta:
        dataclass = ValidationFinding


class ValidationSummarySerializer(DataclassSerializer):
    """Quantitative summary returned alongside validation findings."""

    class Meta:
        dataclass = ValidationSummary


class ValidationReportSerializer(DataclassSerializer):
    """Response shape for ``POST /automl_pipelines/validate/``.

    ``ok`` is true iff no findings have ``block`` severity. The same body shape
    as the create endpoint goes in; this report comes out without persisting
    anything.
    """

    class Meta:
        dataclass = ValidationReport


class AutoMLPipelineRunSerializer(DataclassSerializer):
    """Output shape of one bootstrap / retrain / inference run on a pipeline.

    Durable per-run record — holds the agent's outcome report, EDA summary,
    training summary, and failure reason. The pipeline-detail timeline reads
    these rows directly; the retraining iteration chain threads them via
    ``parent_run_id``.
    """

    class Meta:
        dataclass = AutoMLPipelineRunDTO


class RecordEdaResultInputSerializer(DataclassSerializer):
    """Request body for ``POST /automl_pipelines/{id}/runs/{run_id}/record_eda_result/``.

    Called by the bootstrap agent between ``automl eda`` and ``automl train``.
    The ``eda_result`` payload is schemaless on purpose so the CLI's
    ``eda.yaml`` shape can evolve without forcing a migration.
    """

    class Meta:
        dataclass = RecordEdaResultInput


class RecordBootstrapOutcomeInputSerializer(DataclassSerializer):
    """Request body for ``POST /automl_pipelines/{id}/runs/{run_id}/record_bootstrap_outcome/``.

    Called by the bootstrap agent as the final checkpoint of a run. Flips the
    run to a terminal status and writes the structured markdown outcome report
    surfaced on the pipeline-detail page.
    """

    class Meta:
        dataclass = RecordBootstrapOutcomeInput


class RecordInferenceOutcomeInputSerializer(DataclassSerializer):
    """Request body for ``POST /automl_pipelines/{id}/runs/{run_id}/record_inference_outcome/``.

    Called by the inference agent as the single MCP checkpoint at the end of
    a scoring iteration. Stamps the full ``automl refresh-task`` stdout
    manifest into ``inference_result``; the PostHog-side event-emission step
    reads ``predictions_uri`` out of that blob.
    """

    class Meta:
        dataclass = RecordInferenceOutcomeInput
