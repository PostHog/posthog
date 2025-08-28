from django.db.models import Count, QuerySet

import structlog
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.request import Request

from posthog.models.hog_function_template import HogFunctionTemplate
from posthog.models.hog_functions import HogFunction

logger = structlog.get_logger(__name__)


class HogFunctionMappingTemplateSerializer(serializers.Serializer):
    name = serializers.CharField()
    include_by_default = serializers.BooleanField(required=False, allow_null=True)
    filters = serializers.JSONField(required=False, allow_null=True)
    inputs = serializers.JSONField(required=False, allow_null=True)
    inputs_schema = serializers.JSONField(required=False, allow_null=True)


class HogFunctionTemplateSerializer(serializers.ModelSerializer):
    mapping_templates = HogFunctionMappingTemplateSerializer(many=True, required=False, allow_null=True)
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
            "mapping_templates",
        ]


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
        if self.action == "list":
            types = ["destination"]
            if self.request.GET.get("type"):
                types = [self.request.GET["type"]]
            elif self.request.GET.get("types"):
                types = self.request.GET["types"].split(",")

            queryset = queryset.filter(type__in=types)

            # Don't include deprecated templates when listing
            queryset = queryset.exclude(status="deprecated")

        if self.request.path.startswith("/api/public_hog_function_templates"):
            queryset = queryset.exclude(status="hidden")

        return queryset

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
