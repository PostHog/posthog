"""DRF serializers for AutoML.

Converts DTOs to/from JSON using DataclassSerializer. Field types are
auto-derived from the frozen dataclasses in ``facade/contracts.py``.
"""

from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    AutoMLPipelineDTO,
    CreatePipelineInput,
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
