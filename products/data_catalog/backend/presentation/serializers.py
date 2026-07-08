"""DRF serializers for data_catalog.

These are the source of truth for the generated frontend/MCP types, so every field carries
help_text. ``status`` is exposed as a plain read-only string (not a ChoiceField) to keep it out of
the drf-spectacular enum namespace, where a component named ``Status`` collides across the API.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer

from ..facade.enums import CreatedSource
from ..facade.models import Metric


@extend_schema_field(OpenApiTypes.OBJECT)
class MetricDefinitionField(serializers.JSONField):
    """A machine-readable query (HogQLQuery, TrendsQuery, event node, ...). Typed as a free object."""


@extend_schema_serializer(component_name="DataCatalogMetric")
class MetricSerializer(serializers.ModelSerializer):
    definition = MetricDefinitionField(
        required=False,
        allow_null=True,
        help_text="Machine-readable query. Omit for a name+description-only stub. Stored upgrade-canonical.",
    )
    definition_kind = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Query kind of the definition (HogQLQuery, TrendsQuery, ...), or null for a stub.",
    )
    status = serializers.CharField(
        read_only=True,
        help_text="Persisted lifecycle state: 'proposed' or 'approved'. Drift is reported separately.",
    )
    created_source = serializers.ChoiceField(
        choices=[(s.value, s.value) for s in CreatedSource],
        required=False,
        help_text="Whether a human ('user') or an agent ('ai_generated') authored this metric.",
    )
    owner = serializers.SerializerMethodField(
        help_text="Email of the human accountable for this metric, or null.",
    )
    created_by = UserBasicSerializer(read_only=True, help_text="User who first created this metric.")

    class Meta:
        model = Metric
        fields = [
            "id",
            "name",
            "display_name",
            "description",
            "unit",
            "owner",
            "definition",
            "definition_kind",
            "referenced_table_names",
            "status",
            "approved_at",
            "source_insight_short_id",
            "last_run_at",
            "created_source",
            "ai_model",
            "confidence",
            "reasoning",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "approved_at",
            "referenced_table_names",
            "source_insight_short_id",
            "last_run_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "name": {"help_text": "Identifier-safe run handle, unique per team and reserved forever. Write-once."},
            "display_name": {"help_text": "Human-friendly label. Mutable, unlike name."},
            "description": {"help_text": "What the metric means and how to interpret it."},
            "unit": {"help_text": "Unit of the result, e.g. usd, percent, cents."},
            "ai_model": {"help_text": "Model that generated the metric, if AI-authored."},
            "confidence": {"help_text": "AI author's confidence in the proposal, 0-1."},
            "reasoning": {"help_text": "AI author's reasoning, surfaced as review context."},
        }

    @extend_schema_field(OpenApiTypes.STR)
    def get_owner(self, obj: Metric) -> str | None:
        return obj.owner.email if obj.owner_id else None
