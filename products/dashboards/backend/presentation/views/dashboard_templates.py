from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field, extend_schema_view
from rest_framework import request, response, serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.pagination import FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import PathParameter, TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.event_usage import report_user_action
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.user_permissions import UserPermissions
from posthog.utils import str_to_bool

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.facade import api, contracts
from products.dashboards.backend.facade.enums import DashboardTemplateOrdering, DashboardTemplateScope
from products.dashboards.backend.presentation.dashboard_template_json_schema_parser import dashboard_template_schema
from products.dashboards.backend.presentation.views.dashboard import DashboardCustomizationSerializer

_NON_STAFF_ALLOWED_PATCH_KEYS = frozenset({"template_name", "dashboard_description", "tags", "deleted", "scope"})
_NON_STAFF_FORBIDDEN_CREATE_FIELDS = frozenset({"availability_contexts", "image_url"})
_NON_STAFF_ALLOWED_SCOPES = frozenset({DashboardTemplateScope.ONLY_TEAM, DashboardTemplateScope.ORGANIZATION})


def _non_staff_allowed_scopes_display() -> str:
    """Human-readable list of scopes non-staff editors may set, derived from `_NON_STAFF_ALLOWED_SCOPES`."""
    return " or ".join(sorted(str(scope.value) for scope in _NON_STAFF_ALLOWED_SCOPES))


def _raise_for_rejection[T](call: Callable[[], T]) -> T:
    """Run a facade call, and answer its refusal with a 404 or with the 400 a serializer error gives."""
    try:
        return call()
    except contracts.DashboardTemplateNotFound:
        raise NotFound()
    except contracts.DashboardTemplateWriteRejected as rejected:
        if rejected.field is None:
            raise ValidationError(detail=rejected.message, code=rejected.code)
        raise ValidationError({rejected.field: [rejected.message]}, code=rejected.code)


def _item_count(value: object) -> int:
    return len(value) if isinstance(value, list | dict) else 0


class DashboardTemplatePagination(FacadeLimitOffsetPagination):
    def get_schema_operation_parameters(self, view: Any) -> list[dict[str, Any]]:
        # Like DefaultLimitOffsetPagination, this caps `limit` at `max_limit` but keeps DRF's schema, which
        # states no maximum, so clients generated from the schema keep accepting a larger limit.
        return LimitOffsetPagination.get_schema_operation_parameters(self, view)


class CustomerDashboardTemplateWritePermission(BasePermission):
    """
    Staff: any unsafe method (delegates object rules to has_object_permission).
    Non-staff: only templates owned by the requesting project (team- or org-scoped); global / feature-flag rows
    forbidden. Org-scoped templates stay readable org-wide but writeable only from their owning project.
    Project RBAC is enforced separately by AccessControlPermission (editor on `dashboard_template`).
    """

    message = "You don't have edit permissions for this dashboard template."

    def has_permission(self, request: Request, view) -> bool:
        return True

    def has_object_permission(self, request: Request, view, obj: Any) -> bool:
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if getattr(user, "is_staff", False):
            return True
        if not isinstance(obj, contracts.DashboardTemplate):
            return False
        if obj.scope in (DashboardTemplateScope.GLOBAL, DashboardTemplateScope.FEATURE_FLAG):
            return False
        view_team_id = getattr(view, "team_id", None)
        if view_team_id is None:
            return False
        if obj.scope == DashboardTemplateScope.ONLY_TEAM and obj.team_id is not None and obj.team_id != view_team_id:
            return False
        # Org-scoped templates are readable org-wide, but rename/delete/demote is restricted to the owning
        # project's editors. Every org row keeps its creating team_id, so ownership is always derivable.
        if obj.scope == DashboardTemplateScope.ORGANIZATION and obj.team_id != view_team_id:
            return False
        return True


class NonPortableReferencesSerializer(serializers.Serializer):
    actions = serializers.IntegerField(
        help_text="Count of distinct action references in the template's tiles that are specific to the source project."
    )
    cohorts = serializers.IntegerField(
        help_text="Count of distinct cohort references in the template's tiles that are specific to the source project."
    )
    warehouse_tables = serializers.ListField(
        child=serializers.CharField(),
        help_text="Names of data warehouse tables referenced by the template's tiles that are specific to the source project.",
    )


# The fields keep the types, limits and help texts that the model gave them when this was a ModelSerializer,
# so the OpenAPI schema and the generated clients do not change.
class DashboardTemplateSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    template_name = serializers.CharField(max_length=400, allow_null=True, allow_blank=True, required=False)
    dashboard_description = serializers.CharField(max_length=400, allow_null=True, allow_blank=True, required=False)
    dashboard_filters = serializers.JSONField(allow_null=True, required=False)
    tags = serializers.ListField(child=serializers.CharField(max_length=255), allow_null=True, required=False)
    tiles = serializers.JSONField(allow_null=True, required=False)
    variables = serializers.JSONField(allow_null=True, required=False)
    customization = DashboardCustomizationSerializer(
        required=False,
        allow_null=True,
        help_text=(
            "Display settings that a dashboard made from this template starts with: tile spacing, layout "
            "compaction, and the tile groups that tiles join through their group_key."
        ),
    )
    deleted = serializers.BooleanField(allow_null=True, required=False)
    created_at = serializers.DateTimeField(read_only=True, allow_null=True)
    created_by = UserBasicSerializer(read_only=True)
    image_url = serializers.CharField(max_length=8201, allow_null=True, allow_blank=True, required=False)
    team_id = serializers.IntegerField(read_only=True, allow_null=True)
    scope = serializers.ChoiceField(
        choices=DashboardTemplateScope.choices, allow_null=True, allow_blank=True, required=False
    )
    availability_contexts = serializers.ListField(
        child=serializers.CharField(max_length=255), allow_null=True, required=False
    )
    is_featured = serializers.BooleanField(
        required=False, help_text="Manually curated; used to highlight templates in the UI."
    )
    non_portable_references = serializers.SerializerMethodField(
        help_text=(
            "Read-only. Project-specific references (actions, cohorts, data warehouse tables) embedded in this "
            "template's tiles that may not resolve when it is used in another project. Events and properties are "
            "matched by name and are portable, so they are not reported here."
        ),
    )

    def to_representation(self, instance: contracts.DashboardTemplate) -> dict[str, Any]:
        team = self.context["get_team"]()
        shown = api.dashboard_template_for_display(
            instance, ai_data_processing_approved=bool(team.organization.is_ai_data_processing_approved)
        )
        return super().to_representation(shown)

    @extend_schema_field(NonPortableReferencesSerializer)
    def get_non_portable_references(self, obj: contracts.DashboardTemplate) -> dict[str, Any] | None:
        # O(tiles) per row, so only compute when a single template is fetched (retrieve). List responses — the
        # dashboard chooser and the management table — return null and fetch references on demand when promoting.
        view = self.context.get("view")
        if view is None or getattr(view, "action", None) != "retrieve":
            return None
        return NonPortableReferencesSerializer(api.dashboard_template_non_portable_references(obj)).data

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        is_staff = bool(user and user.is_authenticated and user.is_staff)
        initial = getattr(self, "initial_data", None) or {}
        if not is_staff:
            if self.instance is None:
                forbidden_create = _NON_STAFF_FORBIDDEN_CREATE_FIELDS & set(initial.keys())
                if forbidden_create:
                    raise ValidationError(
                        {
                            k: ["You cannot set this field when creating a project template."]
                            for k in sorted(forbidden_create)
                        }
                    )
            if self.instance is not None:
                forbidden_patch = set(initial.keys()) - _NON_STAFF_ALLOWED_PATCH_KEYS
                if forbidden_patch:
                    raise ValidationError(
                        {
                            k: ["Only name, description, tags, scope, and delete can be changed for project templates."]
                            for k in sorted(forbidden_patch)
                        }
                    )

        if not is_staff:
            if self.instance is None:
                # Create: default to team scope; allow team or organization, reject global / feature-flag.
                requested_scope = attrs.get("scope") or initial.get("scope") or DashboardTemplateScope.ONLY_TEAM
                if requested_scope not in _NON_STAFF_ALLOWED_SCOPES:
                    raise ValidationError(
                        {"scope": [f"Project templates can only use {_non_staff_allowed_scopes_display()} scope."]},
                    )
                is_featured_val = initial.get("is_featured", attrs.get("is_featured"))
                if is_featured_val:
                    raise ValidationError({"is_featured": ["Only staff can mark templates as featured."]})
                attrs["scope"] = requested_scope
                attrs["is_featured"] = False
            elif "scope" in initial:
                # Update: only a team <-> organization transition is allowed for non-staff.
                requested_scope = attrs.get("scope") or initial.get("scope")
                if (
                    self.instance.scope not in _NON_STAFF_ALLOWED_SCOPES
                    or requested_scope not in _NON_STAFF_ALLOWED_SCOPES
                ):
                    raise ValidationError(
                        {"scope": ["You can only switch a template between team and organization visibility."]},
                    )
                attrs["scope"] = requested_scope

        return attrs

    def to_write(self) -> contracts.DashboardTemplateWrite:
        return contracts.DashboardTemplateWrite(fields_set=frozenset(self.validated_data), **self.validated_data)


class CopyDashboardTemplateSerializer(serializers.Serializer):
    source_template_id = serializers.UUIDField(
        help_text="UUID of a team-scoped template in the same organization. Global and feature-flag templates cannot be copied with this endpoint."
    )


def _assert_user_can_read_source_for_copy(*, user: User, source_team_id: int) -> None:
    if user.is_staff:
        return
    up = UserPermissions(user=user)
    if source_team_id not in up.team_ids_visible_for_user:
        raise NotFound()
    source_team = Team.objects.get(pk=source_team_id)
    uac = UserAccessControl(
        user=user,
        team=source_team,
        organization_id=str(source_team.organization_id),
    )
    if not uac.check_access_level_for_resource("dashboard_template", "viewer"):
        raise NotFound()


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description=(
                    "Optional. Full-text search across template name, tags, and description, ranked by relevance. "
                    "Use it to find templates for a topic (e.g. `retention`, `revenue`, `product analytics`)."
                ),
            ),
            OpenApiParameter(
                "ordering",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description=(
                    "Optional. When not using `search`, results are sorted with featured templates first "
                    "(`is_featured=true`), then by `template_name` (case-insensitive A–Z; `-template_name` for Z–A) "
                    "or by `created_at` (`-created_at` for newest first). "
                    "When `search` is set, order is featured first, then relevance rank, then case-insensitive name "
                    "for ties."
                ),
                enum=["template_name", "-template_name", "created_at", "-created_at"],
            ),
            OpenApiParameter(
                "is_featured",
                OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description=(
                    "Omit for all templates. When set, filter by featured flag; parsed with str_to_bool "
                    "(same as other API query booleans)."
                ),
            ),
            OpenApiParameter(
                "scope",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description=(
                    "Optional. `global`: official templates only. `team`: this project's saved templates only "
                    "(`scope=team` rows for the current project). `organization`: templates shared across all projects "
                    "in this organization. `feature_flag`: feature-flag dashboard templates only. "
                    "Omit for official, organization, and this project's templates (default dashboard template picker behavior)."
                ),
                enum=["global", "team", "organization", "feature_flag"],
            ),
        ],
    ),
)
class DashboardTemplateViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.GenericViewSet):
    scope_object = "dashboard_template"
    permission_classes = [CustomerDashboardTemplateWritePermission]
    serializer_class = DashboardTemplateSerializer
    pagination_class = DashboardTemplatePagination
    path_parameters = {
        "pk": PathParameter(type=UUID, description="A UUID string identifying this dashboard template."),
    }
    # No access rule names one template, so AccessControlPermission checks templates at the resource level only.
    records_have_object_access_rules = False

    def _filters(self) -> contracts.DashboardTemplateFilters:
        """The list query params narrow every route, including a retrieve or an update."""
        params = self.request.query_params
        scope = params.get("scope")
        ordering = params.get("ordering")
        is_featured = params.get("is_featured")
        return contracts.DashboardTemplateFilters(
            scope=DashboardTemplateScope(scope) if scope in DashboardTemplateScope.values else None,
            search=params.get("search"),
            ordering=DashboardTemplateOrdering(ordering)
            if ordering and ordering in DashboardTemplateOrdering
            else None,
            is_featured=str_to_bool(is_featured) if is_featured is not None else None,
        )

    def read_object(self) -> contracts.DashboardTemplate | None:
        return api.get_dashboard_template(
            team_id=self.team_id,
            organization_id=self.team.organization_id,
            template_id=self.kwargs["pk"],
            filters=self._filters(),
            include_deleted=self.request.method not in SAFE_METHODS,
        )

    @extend_schema(responses={200: DashboardTemplateSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> response.Response:
        filters = self._filters()
        return facade_page_response(
            self,
            lambda page: api.list_dashboard_templates(
                team_id=self.team_id, organization_id=self.team.organization_id, filters=filters, page=page
            ),
        )

    @extend_schema(responses={200: DashboardTemplateSerializer})
    def retrieve(self, request: Request, pk: UUID, **kwargs) -> response.Response:
        return response.Response(self.get_serializer(self.get_object()).data)

    @extend_schema(request=DashboardTemplateSerializer, responses={201: DashboardTemplateSerializer})
    def create(self, request: Request, **kwargs) -> response.Response:
        serializer = cast(DashboardTemplateSerializer, self.get_serializer(data=request.data))
        serializer.is_valid(raise_exception=True)
        user = request.user if isinstance(request.user, User) else None
        template = _raise_for_rejection(
            lambda: api.create_dashboard_template(
                team_id=self.team_id,
                organization_id=self.team.organization_id,
                created_by_id=user.id if user is not None else None,
                write=serializer.to_write(),
            )
        )
        if template.scope != DashboardTemplateScope.GLOBAL and user is not None:
            report_user_action(
                user,
                "dashboard project template created",
                properties={
                    "template_id": str(template.id),
                    "scope": str(template.scope or ""),
                    "team_id": template.team_id,
                    "organization_id": self.organization_id,
                    "is_staff": bool(user.is_staff),
                    "created_by_id": template.created_by_id,
                    "template_name": template.template_name,
                    "tile_count": _item_count(template.tiles),
                    "variable_count": _item_count(template.variables),
                },
                team=self.team,
                organization=self.organization,
                request=request,
            )
        return response.Response(self.get_serializer(template).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=DashboardTemplateSerializer, responses={200: DashboardTemplateSerializer})
    def update(self, request: Request, pk: UUID, **kwargs) -> response.Response:
        return self._update(request, partial=False)

    @extend_schema(request=DashboardTemplateSerializer, responses={200: DashboardTemplateSerializer})
    def partial_update(self, request: Request, pk: UUID, **kwargs) -> response.Response:
        return self._update(request, partial=True)

    def _update(self, request: Request, *, partial: bool) -> response.Response:
        template: contracts.DashboardTemplate = self.get_object()
        serializer = cast(
            DashboardTemplateSerializer, self.get_serializer(template, data=request.data, partial=partial)
        )
        serializer.is_valid(raise_exception=True)
        updated = _raise_for_rejection(
            lambda: api.update_dashboard_template(
                team_id=self.team_id,
                organization_id=self.team.organization_id,
                template_id=template.id,
                filters=self._filters(),
                write=serializer.to_write(),
            )
        )
        user = request.user
        if updated.scope != template.scope and isinstance(user, User):
            report_user_action(
                user,
                "dashboard template scope changed",
                properties={
                    "template_id": str(updated.id),
                    "from_scope": str(template.scope or ""),
                    "to_scope": str(updated.scope or ""),
                    "team_id": updated.team_id,
                    "organization_id": self.organization_id,
                    "is_staff": bool(user.is_staff),
                },
                team=self.team,
                organization=self.organization,
                request=request,
            )
        return response.Response(self.get_serializer(updated).data)

    @method_decorator(cache_page(60 * 2))  # cache for 2 minutes
    @action(methods=["GET"], detail=False)
    def json_schema(self, request: request.Request, **kwargs) -> response.Response:
        # Could switch from this being a static file to being dynamically generated from the serializer
        return response.Response(dashboard_template_schema)

    @extend_schema(
        request=CopyDashboardTemplateSerializer,
        responses={status.HTTP_201_CREATED: DashboardTemplateSerializer},
        summary="Copy a team template to this project",
        description=(
            "Creates a new team-scoped template in the **target** project (URL) from a **team-scoped** source template "
            "in the same organization. Global and feature-flag templates return 400. Cross-organization or inaccessible "
            "sources return 404. Source and destination projects must differ (400 if equal). "
            "Conflicting `template_name` values on the destination are auto-suffixed with `(copy)`, `(copy 2)`, …"
        ),
    )
    @action(detail=False, methods=["post"], url_path="copy_between_projects")
    def copy_between_projects(self, request: Request, **kwargs) -> response.Response:
        body = CopyDashboardTemplateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        source_template_id = cast(UUID, body.validated_data["source_template_id"])

        target_team = self.team
        target_org_id = cast(UUID, target_team.organization_id)
        source = _raise_for_rejection(
            lambda: api.dashboard_template_copy_source(
                team_id=target_team.id, organization_id=target_org_id, source_template_id=source_template_id
            )
        )

        user = cast(User, request.user)
        _assert_user_can_read_source_for_copy(user=user, source_team_id=cast(int, source.team_id))

        new_template = _raise_for_rejection(
            lambda: api.copy_dashboard_template(
                team_id=target_team.id, organization_id=target_org_id, source=source, created_by_id=user.id
            )
        )

        report_user_action(
            user,
            "dashboard project template copied between projects",
            properties={
                "source_template_id": str(source.id),
                "new_template_id": str(new_template.id),
                "source_team_id": source.team_id,
                "target_team_id": target_team.id,
                "organization_id": str(self.organization_id),
                "template_name": new_template.template_name,
                "tile_count": _item_count(new_template.tiles),
                "variable_count": _item_count(new_template.variables),
            },
            team=self.team,
            organization=self.organization,
            request=request,
        )

        serializer = DashboardTemplateSerializer(new_template, context=self.get_serializer_context())
        return response.Response(serializer.data, status=status.HTTP_201_CREATED)
