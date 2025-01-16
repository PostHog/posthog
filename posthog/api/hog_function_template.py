import structlog
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.exceptions import NotFound

from posthog.cdp.templates import HOG_FUNCTION_SUB_TEMPLATES, HOG_FUNCTION_TEMPLATES, ALL_HOG_FUNCTION_TEMPLATES_BY_ID
from posthog.cdp.templates.hog_function_template import (
    HogFunctionMapping,
    HogFunctionMappingTemplate,
    HogFunctionTemplate,
    HogFunctionSubTemplate,
)
from rest_framework_dataclasses.serializers import DataclassSerializer


logger = structlog.get_logger(__name__)


class HogFunctionMappingSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogFunctionMapping


class HogFunctionMappingTemplateSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogFunctionMappingTemplate


class HogFunctionSubTemplateSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogFunctionSubTemplate


class HogFunctionTemplateSerializer(DataclassSerializer):
    mapping_templates = HogFunctionMappingTemplateSerializer(many=True, required=False)
    mappings = HogFunctionMappingSerializer(many=True, required=False)
    sub_templates = HogFunctionSubTemplateSerializer(many=True, required=False)

    class Meta:
        dataclass = HogFunctionTemplate


# NOTE: There is nothing currently private about these values
class PublicHogFunctionTemplateViewSet(viewsets.GenericViewSet):
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["id", "team", "created_by", "enabled", "type"]
    permission_classes = [permissions.AllowAny]
    serializer_class = HogFunctionTemplateSerializer

    def list(self, request: Request, *args, **kwargs):
        types = ["destination"]

        sub_template_id = request.GET.get("sub_template_id")

        if "type" in request.GET:
            types = [self.request.GET.get("type", "destination")]
        elif "types" in request.GET:
            types = self.request.GET.get("types", "destination").split(",")

        templates_list = HOG_FUNCTION_SUB_TEMPLATES if sub_template_id else HOG_FUNCTION_TEMPLATES

        matching_templates = []

        for template in templates_list:
            if template.type not in types:
                continue

            if sub_template_id and sub_template_id not in template.id:
                continue

            if request.path.startswith("/api/public_hog_function_templates"):
                if "[CDP-TEST-HIDDEN]" in template.name or template.status == "alpha":
                    continue

            matching_templates.append(template)

        page = self.paginate_queryset(matching_templates)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    def retrieve(self, request: Request, *args, **kwargs):
        item = ALL_HOG_FUNCTION_TEMPLATES_BY_ID.get(kwargs["pk"], None)

        if not item:
            raise NotFound(f"Template with id {kwargs['pk']} not found.")

        serializer = self.get_serializer(item)
        return Response(serializer.data)
