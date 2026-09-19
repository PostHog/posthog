from functools import cached_property

from django.db.models import Count, QuerySet

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.request import Request

from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.cdp.flag_gated_templates import FLAG_GATED_TEMPLATE_IDS, hidden_gated_template_ids
from posthog.models.team import Team
from posthog.models.user import User
from posthog.permissions import APIScopePermission

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions import HogFunction

logger = structlog.get_logger(__name__)


class HogFunctionMappingTemplateSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Name of this mapping template.")
    include_by_default = serializers.BooleanField(
        required=False, allow_null=True, help_text="Whether this mapping is enabled by default."
    )
    use_all_events_by_default = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Whether this mapping should match all events by default, hiding the event filter UI.",
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
@extend_schema(tags=["hog_function_templates"], extensions={"x-product": "cdp"})
class PublicHogFunctionTemplateViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "hog_function"
    serializer_class = HogFunctionTemplateSerializer
    queryset = HogFunctionTemplate.objects.all()
    lookup_field = "template_id"
    # Plain GenericViewSet doesn't inherit TeamAndOrgViewSetMixin's authenticators, so the global
    # default (SessionAuthentication only) applies. Declare the API-token authenticators explicitly
    # so personal API key / OAuth callers (the MCP server, public API) can reach the authenticated
    # project-nested mount — without these, IsAuthenticated rejects every non-cookie request as 401.
    authentication_classes = [
        OAuthAccessTokenAuthentication,
        PersonalAPIKeyAuthentication,
        SessionAuthentication,
    ]

    @cached_property
    def team(self) -> Team:
        # APIScopePermission resolves `view.team` to enforce a token's `scoped_teams`/`scoped_organizations`
        # and org-level key restrictions. This viewset isn't a TeamAndOrgViewSetMixin, so provide the
        # minimal resolution from the project-nested URL kwarg ourselves.
        project_id = self.kwargs.get("parent_lookup_project_id")
        if project_id == "@current":
            user = self.request.user
            if isinstance(user, User) and user.team is not None:
                return user.team
            raise NotFound("Project not found.")
        try:
            return Team.objects.select_related("organization").get(id=project_id)
        except (Team.DoesNotExist, ValueError, TypeError):
            raise NotFound("Project not found.")

    def get_permissions(self):
        # The dedicated public catalog endpoint is intentionally anonymous. The project-nested
        # mount is part of the authenticated app and must not expose templates (including hidden
        # ones) to anonymous callers.
        if self.request.path.startswith("/api/public_hog_function_templates"):
            return [permissions.AllowAny()]
        # IsAuthenticated blocks anonymous callers; APIScopePermission enforces the `hog_function`
        # scope (and team/org scoping) for personal API key / OAuth tokens. IsAuthenticated must stay
        # first — APIScopePermission alone treats credential-less requests as session auth and allows them.
        return [permissions.IsAuthenticated(), APIScopePermission()]

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

            queryset = queryset.exclude(status="deprecated")

            # Hidden templates (e.g. template-posthog-capture, template-posthog-update-person-properties,
            # email, twilio, webhook) are internal building blocks. The workflow editor needs them on
            # the authenticated project mount to render action configuration; the frontend hides them
            # from the destinations chooser separately. Only strip them from the anonymous catalog.
            if self.request.path.startswith("/api/public_hog_function_templates"):
                queryset = queryset.exclude(status="hidden")
                queryset = queryset.exclude(template_id__in=list(FLAG_GATED_TEMPLATE_IDS))
            else:
                # Flag-gated pre-release templates stay invisible to teams without the flag, so an
                # agent listing templates can't discover a step that workflow validation would then
                # reject as "Template not found".
                gated_ids = hidden_gated_template_ids(self.team)
                if gated_ids:
                    queryset = queryset.exclude(template_id__in=gated_ids)

        return queryset

    def _template_ids_by_popularity(self, queryset: QuerySet) -> list[str]:
        template_usage = (
            HogFunction.objects.filter(deleted=False, enabled=True, template_id__in=queryset.values("template_id"))
            .values("template_id")
            .annotate(count=Count("template_id"))
        )
        popularity = {item["template_id"]: item["count"] for item in template_usage}

        templates = list(queryset.values_list("template_id", "name"))
        # template_id is the final tie-breaker, so templates with the same usage and name keep one order.
        templates.sort(key=lambda template: (-popularity.get(template[0], 0), template[1].lower(), template[0]))

        return [template_id for template_id, _ in templates]

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
        queryset = self.filter_queryset(self.get_queryset())
        # The catalog can be bigger than one page, so the full result set is ordered before it is
        # paginated. An unordered queryset lets the database pick the page boundaries, which can
        # drop a template from every page or repeat it on two of them.
        ordered_template_ids = self._template_ids_by_popularity(queryset)

        page_template_ids = self.paginate_queryset(ordered_template_ids)

        templates = {template.template_id: template for template in queryset.filter(template_id__in=page_template_ids)}
        page = [templates[template_id] for template_id in page_template_ids if template_id in templates]

        return self.get_paginated_response(self.get_serializer(page, many=True).data)
