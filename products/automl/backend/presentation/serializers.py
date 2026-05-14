"""DRF serializers for AutoML.

Converts DTOs to/from JSON using DataclassSerializer. Field types are
auto-derived from the frozen dataclasses in ``facade/contracts.py``.
"""

from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    AutoMLModelVersionDTO,
    AutoMLPipelineDTO,
    CreatePipelineInput,
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
