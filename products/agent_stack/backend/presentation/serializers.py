"""DRF serializers for agent_stack."""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import SplineReticulatorDTO


class SplineReticulatorSerializer(DataclassSerializer):
    class Meta:
        dataclass = SplineReticulatorDTO


class CreateSplineReticulatorSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="Name of the spline to reticulate.")
