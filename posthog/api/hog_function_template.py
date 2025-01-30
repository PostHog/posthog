from datetime import datetime, timedelta
from posthoganalytics import capture_exception
import structlog
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.exceptions import NotFound

from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES
from posthog.cdp.templates.hog_function_template import (
    HogFunctionMapping,
    HogFunctionMappingTemplate,
    HogFunctionTemplate,
    HogFunctionSubTemplate,
    derive_sub_templates,
)
from posthog.plugins.plugin_server_api import get_hog_function_templates
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


class HogFunctionTemplates:
    _cache_until: datetime | None = None
    _cached_templates: list[HogFunctionTemplate] = []
    _cached_templates_by_id: dict[str, HogFunctionTemplate] = {}
    _cached_sub_templates: list[HogFunctionTemplate] = []
    _cached_sub_templates_by_id: dict[str, HogFunctionTemplate] = {}

    @classmethod
    def templates(cls):
        cls._load_templates()
        return cls._cached_templates

    @classmethod
    def sub_templates(cls):
        cls._load_templates()
        return cls._cached_sub_templates

    @classmethod
    def template(cls, template_id: str):
        cls._load_templates()
        return cls._cached_templates_by_id.get(template_id, cls._cached_sub_templates_by_id.get(template_id))

    @classmethod
    def _load_templates(cls):
        if cls._cache_until and datetime.now() < cls._cache_until:
            return

        # First we load and convert all nodejs templates to python templates
        nodejs_templates: list[HogFunctionTemplate] = []

        try:
            response = get_hog_function_templates()

            if response.status_code != 200:
                raise Exception("Failed to fetch hog function templates from the node service")

            nodejs_templates_json = response.json()
            for template_data in nodejs_templates_json:
                try:
                    serializer = HogFunctionTemplateSerializer(data=template_data)
                    serializer.is_valid(raise_exception=True)
                    template = serializer.save()
                    nodejs_templates.append(template)
                except Exception as e:
                    logger.error(
                        "Failed to convert template",
                        template_id=template_data.get("id"),
                        error=str(e),
                        exc_info=True,
                    )
                    capture_exception(e)
                    raise
        except Exception as e:
            capture_exception(e)
            # Continue on so as not to block the user

        templates = [
            *HOG_FUNCTION_TEMPLATES,
            *nodejs_templates,
        ]
        sub_templates = derive_sub_templates(templates=templates)

        # If we failed to get the templates, we cache for 30 seconds to avoid hammering the node service
        # If we got the templates, we cache for 5 minutes as these change infrequently
        cls._cache_until = datetime.now() + timedelta(seconds=30 if not nodejs_templates else 300)
        cls._cached_templates = templates
        cls._cached_sub_templates = sub_templates
        cls._cached_templates_by_id = {template.id: template for template in templates}
        cls._cached_sub_templates_by_id = {template.id: template for template in sub_templates}


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

        templates_list = HogFunctionTemplates.sub_templates() if sub_template_id else HogFunctionTemplates.templates()

        matching_templates = []

        for template in templates_list:
            if template.type not in types:
                continue

            if sub_template_id and sub_template_id not in template.id:
                continue

            if request.path.startswith("/api/public_hog_function_templates"):
                if template.status == "alpha":
                    continue

            matching_templates.append(template)

        page = self.paginate_queryset(matching_templates)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    def retrieve(self, request: Request, *args, **kwargs):
        item = HogFunctionTemplates.template(kwargs["pk"])

        if not item:
            raise NotFound(f"Template with id {kwargs['pk']} not found.")

        serializer = self.get_serializer(item)
        return Response(serializer.data)
