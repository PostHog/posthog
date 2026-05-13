"""DRF serializers for AutoML.

Converts DTOs to/from JSON using DataclassSerializer. Field types are
auto-derived from the frozen dataclasses in ``facade/contracts.py``.
"""

from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import AutoMLPipelineDTO, CreatePipelineInput, UpdatePipelineInput


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
