from django.db.models import Count, QuerySet

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.request import Request

from posthog.models.hog_function_template import HogFunctionTemplate
from posthog.models.hog_functions import HogFunction

logger = structlog.get_logger(__name__)


class HogFunctionMappingTemplateSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Name of this mapping template.")
    include_by_default = serializers.BooleanField(
        required=False, allow_null=True, help_text="Whether this mapping is enabled by default."
    )
    filters = serializers.JSONField(
        required=False, allow_null=True, help_text="Event filters specific to this mapping."
    )
    inputs = serializers.JSONField(required=False, allow_null=True, help_text="Input values specific to this mapping.")
    inputs_schema = serializers.JSONField(
        required=False, allow_null=True, help_text="Additional input schema fields specific to this mapping."
    )


class HogFunctionTemplateSerializer(serializers.ModelSerializer):
    mapping_templates = HogFunctionMappingTemplateSerializer(
        many=True,
        required=False,
        allow_null=True,
        help_text="Pre-defined mapping configurations for destination templates.",
    )
    id = serializers.CharField(source="template_id", help_text="Unique template identifier (e.g. 'template-slack').")

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
            "mapping_templates",
        ]
        extra_kwargs = {
            "name": {"help_text": "Display name of the template."},
            "description": {"help_text": "What this template does."},
            "code": {"help_text": "Source code of the template."},
            "code_language": {"help_text": "Programming language: 'hog' or 'javascript'."},
            "inputs_schema": {
                "help_text": "Schema defining configurable inputs for functions created from this template."
            },
            "type": {"help_text": "Function type this template creates."},
            "status": {"help_text": "Lifecycle status: alpha, beta, stable, deprecated, or hidden."},
            "category": {"help_text": "Category tags for organizing templates."},
            "free": {"help_text": "Whether available on free plans."},
            "icon_url": {"help_text": "URL for the template's icon."},
            "filters": {"help_text": "Default event filters."},
            "masking": {"help_text": "Default PII masking configuration."},
        }


# NOTE: There is nothing currently private about these values
@extend_schema(tags=["hog_function_templates", "cdp"])
class PublicHogFunctionTemplateViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "hog_function"
    permission_classes = [permissions.AllowAny]
    serializer_class = HogFunctionTemplateSerializer
    queryset = HogFunctionTemplate.objects.all()
    lookup_field = "template_id"

    def filter_queryset(self, queryset: QuerySet) -> QuerySet:
        if self.action == "list":
            types = ["destination"]
            if self.request.GET.get("type"):
                types = [self.request.GET["type"]]
            elif self.request.GET.get("types"):
                types = self.request.GET["types"].split(",")

            queryset = queryset.filter(type__in=types)

            if self.request.GET.get("template_id"):
                queryset = queryset.filter(template_id=self.request.GET["template_id"])

            # Don't include deprecated templates when listing
            queryset = queryset.exclude(status="deprecated")

        if self.request.path.startswith("/api/public_hog_function_templates"):
            queryset = queryset.exclude(status="hidden")

        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "type",
                OpenApiTypes.STR,
                description="Filter by template type (e.g. destination, email, sms_provider, broadcast). Defaults to destination if neither type nor types is provided.",
            ),
            OpenApiParameter(
                "types",
                OpenApiTypes.STR,
                description="Comma-separated list of template types to include (e.g. destination,email,sms_provider).",
            ),
            OpenApiParameter(
                "template_id",
                OpenApiTypes.STR,
                description="Filter to a specific template by its template_id. Deprecated templates are excluded from list results; use the retrieve endpoint to look up a template by ID regardless of status.",
            ),
        ]
    )
    def list(self, request: Request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)

        # Load the counts of usage for these templates and re-order the results by usage
        results = response.data["results"]
        template_ids = [result["id"] for result in results]

        template_usage = (
            HogFunction.objects.filter(deleted=False, enabled=True, template_id__in=template_ids)
            .values("template_id")
            .annotate(count=Count("template_id"))
            .order_by("-count")[:500]
        )

        popularity_dict = {item["template_id"]: item["count"] for item in template_usage}

        for result in results:
            if result["id"] not in popularity_dict:
                popularity_dict[result["id"]] = 0

        results.sort(key=lambda template: (-popularity_dict[template["id"]], template["name"].lower()))

        response.data["results"] = results

        return response
