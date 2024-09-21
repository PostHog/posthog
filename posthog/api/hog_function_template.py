import structlog
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.exceptions import NotFound

from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES
from posthog.cdp.templates.hog_function_template import HogFunctionTemplate, HogFunctionSubTemplate
from rest_framework_dataclasses.serializers import DataclassSerializer


logger = structlog.get_logger(__name__)


class HogFunctionSubTemplateSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogFunctionSubTemplate


class HogFunctionTemplateSerializer(DataclassSerializer):
    sub_templates = HogFunctionSubTemplateSerializer(many=True, required=False)

    class Meta:
        dataclass = HogFunctionTemplate


# NOTE: There is nothing currently private about these values
class PublicHogFunctionTemplateViewSet(viewsets.GenericViewSet):
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["id", "team", "created_by", "enabled"]
    permission_classes = [permissions.AllowAny]
    serializer_class = HogFunctionTemplateSerializer

    def _get_templates(self):
        data = HOG_FUNCTION_TEMPLATES
        return data

    def list(self, request: Request, *args, **kwargs):
        page = self.paginate_queryset(self._get_templates())
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    def retrieve(self, request: Request, *args, **kwargs):
        data = self._get_templates()
        item = next((item for item in data if item.id == kwargs["pk"]), None)

        if not item:
            raise NotFound(f"Template with id {kwargs['pk']} not found.")

        serializer = self.get_serializer(item)
        return Response(serializer.data)
