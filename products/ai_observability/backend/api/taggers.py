from typing import Any

from django.core.validators import EMPTY_VALUES
from django.db.models import Q, QuerySet

import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.monitoring import Feature, monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.utils import strict_fetch
from posthog.permissions import AccessControlPermission, PostHogFeatureFlagPermission

from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin

from ..models.model_configuration import LLMModelConfiguration
from ..models.provider_keys import llm_completion_provider_choices
from ..models.taggers import Tagger, TaggerType
from .condition_sets import ConditionSetSerializer
from .metrics import llma_track_latency


class TagDefinitionSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, help_text="Tag identifier")
    description = serializers.CharField(
        max_length=500, required=False, default="", allow_blank=True, help_text="Description to help the LLM classify"
    )


class TaggerConditionSerializer(ConditionSetSerializer):
    id = serializers.CharField(max_length=100, help_text="Stable identifier for this condition")
    rollout_percentage = serializers.FloatField(
        default=100,
        min_value=0,
        max_value=100,
        help_text="Percentage of matching events to apply this condition to",
    )
    properties = serializers.ListField(
        child=serializers.DictField(),
        default=list,
        help_text="Property filters that scope when this condition fires",
    )


class LLMTaggerConfigSerializer(serializers.Serializer):
    prompt = serializers.CharField(min_length=1, help_text="Prompt instructing the LLM how to tag generations")
    tags = TagDefinitionSerializer(many=True, help_text="Available tags the LLM can assign")
    min_tags = serializers.IntegerField(default=0, min_value=0, help_text="Minimum number of tags to apply")
    max_tags = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, help_text="Maximum number of tags to apply (null = no limit)"
    )


class HogTaggerConfigSerializer(serializers.Serializer):
    source = serializers.CharField(  # type: ignore[assignment]
        min_length=1,
        help_text="Hog source code to classify a generation into tags.",
    )
    tags = TagDefinitionSerializer(
        many=True,
        required=False,
        default=list,
        help_text="Optional tag whitelist. Leave empty to allow any tag returned by the Hog code.",
    )


TAGGER_CONFIG_SCHEMA = PolymorphicProxySerializer(
    component_name="TaggerConfig",
    serializers=[LLMTaggerConfigSerializer, HogTaggerConfigSerializer],
    resource_type_field_name=None,
)


@extend_schema_field(TAGGER_CONFIG_SCHEMA)
class TaggerConfigField(serializers.JSONField):
    pass


class TaggerModelConfigurationSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(
        choices=llm_completion_provider_choices(), help_text="LLM provider to use for this tagger."
    )
    model = serializers.CharField(max_length=100, help_text="Provider model identifier to use for this tagger.")
    provider_key_id = serializers.UUIDField(
        allow_null=True, help_text="LLM provider key UUID pinned for this tagger, or null when none is pinned."
    )
    provider_key_name = serializers.SerializerMethodField(read_only=True)

    def get_provider_key_name(self, obj: LLMModelConfiguration) -> str | None:
        if obj.provider_key:
            return obj.provider_key.name
        return None

    def to_representation(self, instance: LLMModelConfiguration) -> dict[str, Any]:
        return {
            "provider": instance.provider,
            "model": instance.model,
            "provider_key_id": str(instance.provider_key_id) if instance.provider_key_id else None,
            "provider_key_name": instance.provider_key.name if instance.provider_key else None,
        }


class TaggerSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    model_configuration = TaggerModelConfigurationSerializer(read_only=True, allow_null=True)
    tagger_config = TaggerConfigField(
        read_only=True,
        help_text=(
            "Tagger configuration. For tagger_type 'llm': {prompt, tags, min_tags?, max_tags?}. "
            "For tagger_type 'hog': {source, tags?}."
        ),
    )
    tagger_type = serializers.ChoiceField(choices=TaggerType.choices, read_only=True)
    conditions = TaggerConditionSerializer(
        many=True, read_only=True, help_text="Conditions that scoped when the tagger ran"
    )
    migrated_to_evaluation_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="The evaluation that replaced this tagger when it was migrated. Null until then.",
    )

    class Meta:
        model = Tagger
        fields = [
            "id",
            "name",
            "description",
            "enabled",
            "tagger_type",
            "tagger_config",
            "conditions",
            "model_configuration",
            "created_at",
            "updated_at",
            "created_by",
            "deleted",
            "migrated_to_evaluation_id",
        ]
        read_only_fields = fields


class StableOrderingFilter(django_filters.OrderingFilter):
    """Append the primary key so tied rows keep a total order across paginated requests."""

    def filter(self, qs: QuerySet, value: Any) -> QuerySet:
        ordering = [self.get_ordering_value(param) for param in value or [] if param not in EMPTY_VALUES]
        if not ordering:
            return qs

        return qs.order_by(*ordering, "id")


class TaggerFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(method="filter_search", help_text="Search in name or description")
    enabled = django_filters.BooleanFilter(help_text="Filter by enabled status")
    migrated_to_evaluation_id = django_filters.UUIDFilter(
        help_text="Only the tagger that was migrated to this evaluation"
    )
    order_by = StableOrderingFilter(
        fields=(
            ("created_at", "created_at"),
            ("updated_at", "updated_at"),
            ("name", "name"),
        ),
        field_labels={
            "created_at": "Created At",
            "updated_at": "Updated At",
            "name": "Name",
        },
    )

    class Meta:
        model = Tagger
        fields = {
            "id": ["in"],
            "enabled": ["exact"],
        }

    def filter_search(self, queryset: QuerySet, name: str, value: str) -> QuerySet:
        if value:
            return queryset.filter(Q(name__icontains=value) | Q(description__icontains=value))
        return queryset


# Taggers are deprecated in favor of categorical evaluations, so the API only reads them.
class TaggerViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "tagger"
    permission_classes = [IsAuthenticated, AccessControlPermission, PostHogFeatureFlagPermission]
    posthog_feature_flag = "llm-analytics-tags"
    serializer_class = TaggerSerializer
    queryset = Tagger.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = TaggerFilter

    def safely_get_queryset(self, queryset: QuerySet[Tagger]) -> QuerySet[Tagger]:
        queryset = (
            queryset.filter(team_id=self.team_id, deleted=False)
            .select_related("created_by", "model_configuration", "model_configuration__provider_key")
            .order_by("-created_at", "id")
        )
        if self.action == "list":
            queryset = strict_fetch(queryset)
        return queryset

    @llma_track_latency("llma_taggers_list")
    @monitor(feature=Feature.QUERY, endpoint="llma_taggers_list", method="GET")
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @llma_track_latency("llma_taggers_retrieve")
    @monitor(feature=Feature.QUERY, endpoint="llma_taggers_retrieve", method="GET")
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().retrieve(request, *args, **kwargs)
