import structlog
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.exceptions import NotFound

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES
from posthog.cdp.templates.hog_function_template import HogFunctionTemplate, HogFunctionSubTemplate
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.permissions import PostHogFeatureFlagPermission
from rest_framework_dataclasses.serializers import DataclassSerializer


logger = structlog.get_logger(__name__)


class HogFunctionSubTemplateSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogFunctionSubTemplate


class HogFunctionTemplateSerializer(DataclassSerializer):
    sub_templates = HogFunctionSubTemplateSerializer(many=True, required=False)

    class Meta:
        dataclass = HogFunctionTemplate


class HogFunctionTemplateViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"  # Keep internal until we are happy to release this GA
    queryset = HogFunction.objects.none()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["id", "team", "created_by", "enabled"]

    permission_classes = [PostHogFeatureFlagPermission]
    posthog_feature_flag = {"hog-functions": ["create", "partial_update", "update"]}

    serializer_class = HogFunctionTemplateSerializer

    def _get_templates(self):
        # TODO: Filtering for status?
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
