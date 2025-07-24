import structlog
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, permissions, mixins
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

    class Meta:
        model = HogFunctionTemplate
        fields = [
            "id",
            "template_id",
            "sha",
            "name",
            "description",
            "code",
            "code_language",
            "inputs_schema",
            "bytecode",
            "type",
            "status",
            "category",
            "kind",
            "free",
            "icon_url",
            "filters",
            "masking",
            "mappings",
            "mapping_templates",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_id(self, obj):
        return obj.template_id


# NOTE: There is nothing currently private about these values
class PublicHogFunctionTemplateViewSet(viewsets.ModelViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["id", "team", "created_by", "enabled", "type"]
    permission_classes = [permissions.AllowAny]
    serializer_class = HogFunctionTemplateSerializer
    queryset = HogFunctionTemplate.objects.all()

    # def list(self, request: Request, **kwargs):
    #     types = ["destination"]
    #     sub_template_id = request.GET.get("sub_template_id")

    #     if "type" in request.GET:
    #         types = [self.request.GET.get("type", "destination")]
    #     elif "types" in request.GET:
    #         types = self.request.GET.get("types", "destination").split(",")

    #     templates_list = HogFunctionTemplates.templates_from_db()

    #     matching_templates = []

    #     for template in templates_list:
    #         if template.type not in types:
    #             continue

    #         if sub_template_id and sub_template_id not in template.id:
    #             continue

    #         if template.status == "deprecated":
    #             continue

    #         if request.path.startswith("/api/public_hog_function_templates"):
    #             if template.status == "hidden":
    #                 continue

    #         matching_templates.append(template)

    #     if sub_template_id is None:
    #         key = f"hog_function/template_usage"
    #         template_usage = cache.get(key)

    #         if template_usage is None:
    #             template_usage = (
    #                 HogFunction.objects.filter(type="destination", deleted=False, enabled=True)
    #                 .values("template_id")
    #                 .annotate(count=Count("template_id"))
    #                 .order_by("-count")[:500]
    #             )

    #         cache.set(key, template_usage, 60)

    #         popularity_dict = {item["template_id"]: item["count"] for item in template_usage}

    #         for template in matching_templates:
    #             if template.id not in popularity_dict:
    #                 popularity_dict[template.id] = 0

    #         matching_templates.sort(key=lambda template: (-popularity_dict[template.id], template.name.lower()))

    #     page = self.paginate_queryset(matching_templates)
    #     serializer = self.get_serializer(page, many=True)
    #     return self.get_paginated_response(serializer.data)
