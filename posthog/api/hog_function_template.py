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
)
from posthog.plugins.plugin_server_api import get_hog_function_templates
from rest_framework_dataclasses.serializers import DataclassSerializer
from django.db.models import Count
from posthog.models import HogFunction
from django.core.cache import cache
from posthog.models.hog_function_template import HogFunctionTemplate as DBHogFunctionTemplate


logger = structlog.get_logger(__name__)


class HogFunctionMappingSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogFunctionMapping


class HogFunctionMappingTemplateSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogFunctionMappingTemplate


class HogFunctionTemplateSerializer(DataclassSerializer):
    mapping_templates = HogFunctionMappingTemplateSerializer(many=True, required=False)
    mappings = HogFunctionMappingSerializer(many=True, required=False)

    class Meta:
        dataclass = HogFunctionTemplate


class HogFunctionTemplates:
    _cache_until: datetime | None = None
    _cached_templates: list[HogFunctionTemplate] = []
    _cached_templates_by_id: dict[str, HogFunctionTemplate] = {}

    @classmethod
    def templates(cls):
        cls._load_templates()
        return cls._cached_templates

    @classmethod
    def template(cls, template_id: str):
        cls._load_templates()
        return cls._cached_templates_by_id.get(template_id)

    @classmethod
    def templates_from_db(cls):
        db_templates = DBHogFunctionTemplate.get_latest_templates()
        return [template.to_dataclass() for template in db_templates]

    @classmethod
    def template_from_db(cls, template_id: str):
        # Check if it's a regular template
        db_template = DBHogFunctionTemplate.get_template(template_id)
        if db_template:
            return db_template.to_dataclass()

        return None

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
        except Exception as e:
            capture_exception(e)
            # Continue on so as not to block the user

        templates = [
            *HOG_FUNCTION_TEMPLATES,
            *nodejs_templates,
        ]

        # If we failed to get the templates, we cache for 30 seconds to avoid hammering the node service
        # If we got the templates, we cache for 5 minutes as these change infrequently
        cls._cache_until = datetime.now() + timedelta(seconds=30 if not nodejs_templates else 300)
        cls._cached_templates = templates
        cls._cached_templates_by_id = {template.id: template for template in templates}


# NOTE: There is nothing currently private about these values
class PublicHogFunctionTemplateViewSet(viewsets.GenericViewSet):
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["id", "team", "created_by", "enabled", "type"]
    permission_classes = [permissions.AllowAny]
    serializer_class = HogFunctionTemplateSerializer

    def list(self, request: Request, **kwargs):
        types = ["destination"]
        sub_template_id = request.GET.get("sub_template_id")

        if "type" in request.GET:
            types = [self.request.GET.get("type", "destination")]
        elif "types" in request.GET:
            types = self.request.GET.get("types", "destination").split(",")

        templates_list = HogFunctionTemplates.templates_from_db()

        matching_templates = []

        for template in templates_list:
            if template.type not in types:
                continue

            if sub_template_id and sub_template_id not in template.id:
                continue

            if template.status == "deprecated":
                continue

            if request.path.startswith("/api/public_hog_function_templates"):
                if template.status == "hidden":
                    continue

            matching_templates.append(template)

        if sub_template_id is None:
            key = f"hog_function/template_usage"
            template_usage = cache.get(key)

            if template_usage is None:
                template_usage = (
                    HogFunction.objects.filter(type="destination", deleted=False, enabled=True)
                    .values("template_id")
                    .annotate(count=Count("template_id"))
                    .order_by("-count")[:500]
                )

            cache.set(key, template_usage, 60)

            popularity_dict = {item["template_id"]: item["count"] for item in template_usage}

            for template in matching_templates:
                if template.id not in popularity_dict:
                    popularity_dict[template.id] = 0

            matching_templates.sort(key=lambda template: (-popularity_dict[template.id], template.name.lower()))

        page = self.paginate_queryset(matching_templates)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    def retrieve(self, request: Request, **kwargs):
        template_id = kwargs["pk"]

        item = HogFunctionTemplates.template_from_db(template_id)

        if not item:
            raise NotFound(f"Template with id {template_id} not found.")

        serializer = self.get_serializer(item)
        return Response(serializer.data)
