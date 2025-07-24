import structlog
from django.db.models import QuerySet
from rest_framework import permissions, mixins, viewsets
from rest_framework import serializers

from posthog.cdp.templates.hog_function_template import (
    HogFunctionMapping,
    HogFunctionMappingTemplate,
)
from rest_framework_dataclasses.serializers import DataclassSerializer
from posthog.models.hog_function_template import HogFunctionTemplate


logger = structlog.get_logger(__name__)


class HogFunctionMappingSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogFunctionMapping


class HogFunctionMappingTemplateSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogFunctionMappingTemplate


class HogFunctionTemplateSerializer(serializers.ModelSerializer):
    mapping_templates = HogFunctionMappingTemplateSerializer(many=True, required=False)
    mappings = HogFunctionMappingSerializer(many=True, required=False)
    id = serializers.CharField(source="template_id")

    class Meta:
        model = HogFunctionTemplate
        fields = [
            "id",
            "name",
            "description",
            "code",
            "code_language",
            "inputs_schema",
            "type",
            "status",
            "category",
            "free",
            "icon_url",
            "filters",
            "masking",
            "mappings",
            "mapping_templates",
        ]
        read_only_fields = fields


# NOTE: There is nothing currently private about these values
class PublicHogFunctionTemplateViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [permissions.AllowAny]
    serializer_class = HogFunctionTemplateSerializer
    queryset = HogFunctionTemplate.objects.all()
    lookup_field = "template_id"

    # TODO

    def filter_queryset(self, queryset: QuerySet) -> QuerySet:
        types = ["destination"]
        if self.request.GET.get("type"):
            types = [self.request.GET.get("type")]
        elif self.request.GET.get("types"):
            types = self.request.GET.get("types").split(",")

        queryset = queryset.filter(type__in=types)

        # Don't include deprecated templates when listing
        if self.action == "list":
            queryset = queryset.exclude(status="deprecated")

        if self.request.path.startswith("/api/public_hog_function_templates"):
            queryset = queryset.exclude(status="hidden")

        return queryset
