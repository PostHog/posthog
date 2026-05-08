import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NoReturn, cast
from uuid import UUID

from django.db import IntegrityError
from django.db.models import Q
from django.db.models.expressions import OrderBy
from django.db.models.functions import Lower
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

import structlog
import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import request, response, serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.event_usage import report_user_action
from posthog.helpers.full_text_search import build_rank
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.permissions import get_organization_from_view
from posthog.rbac.user_access_control import UserAccessControl
from posthog.user_permissions import UserPermissions
from posthog.utils import str_to_bool

from products.dashboards.backend.models.dashboard_templates import DashboardTemplate

logger = structlog.get_logger(__name__)

# Keep in sync with frontend `FEATURE_FLAGS.CUSTOMER_DASHBOARD_TEMPLATE_AUTHORING`
CUSTOMER_DASHBOARD_TEMPLATE_AUTHORING_FLAG = "customer-dashboard-template-authoring"

# arbitary limit, just to prevent abuse
MAX_DASHBOARD_TEMPLATES_PER_ORGANIZATION = 100

_NON_STAFF_ALLOWED_PATCH_KEYS = frozenset({"template_name", "dashboard_description", "tags", "deleted"})
_NON_STAFF_FORBIDDEN_CREATE_FIELDS = frozenset({"availability_contexts", "image_url", "github_url"})

# load dashboard_template_schema.json
dashboard_template_schema = json.loads((Path(__file__).parent / "dashboard_template_schema.json").read_text())


def organization_dashboard_template_limit_detail() -> str:
    return (
        f"Your organization has reached the limit of {MAX_DASHBOARD_TEMPLATES_PER_ORGANIZATION} dashboard templates. "
        "Delete a template before creating or restoring another."
    )


def count_active_dashboard_templates_for_organization(organization_id: UUID) -> int:
    """Non-deleted templates whose team belongs to the organization (excludes global rows with no team)."""
    return DashboardTemplate.objects.filter(team__organization_id=organization_id).count()


def enforce_organization_dashboard_template_limit(*, organization_id: UUID) -> None:
    if count_active_dashboard_templates_for_organization(organization_id) >= MAX_DASHBOARD_TEMPLATES_PER_ORGANIZATION:
        raise ValidationError(detail=organization_dashboard_template_limit_detail())


def _dashboard_template_list_order_by(ordering: str | None) -> list[Any]:
    """Featured rows first, then order by `template_name` or `created_at` (when `ordering` requests it)."""
    if ordering == "-template_name":
        return ["-is_featured", OrderBy(Lower("template_name"), descending=True)]
    if ordering == "created_at":
        return ["-is_featured", "created_at"]
    if ordering == "-created_at":
        return ["-is_featured", "-created_at"]
    return ["-is_featured", Lower("template_name")]


class CustomerDashboardTemplateWritePermission(BasePermission):
    """
    Staff: any unsafe method (delegates object rules to has_object_permission).
    Non-staff: org-level authoring feature flag (see CUSTOMER_DASHBOARD_TEMPLATE_AUTHORING_FLAG).
    Project RBAC for this resource is enforced separately by AccessControlPermission (editor on `dashboard_template`).
    """

    message = "You don't have edit permissions for this dashboard template."

    def has_permission(self, request: Request, view) -> bool:
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if getattr(user, "is_staff", False):
            return True
        organization = get_organization_from_view(view)
        org_id = str(organization.id)
        user_orm = cast(User, user)
        distinct_id = user_orm.distinct_id or str(user_orm.uuid)
        if not posthoganalytics.feature_enabled(
            CUSTOMER_DASHBOARD_TEMPLATE_AUTHORING_FLAG,
            distinct_id,
            groups={"organization": org_id},
            group_properties={"organization": {"id": org_id}},
            only_evaluate_locally=False,
        ):
            return False
        return True

    def has_object_permission(self, request: Request, view, obj: Any) -> bool:
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if getattr(user, "is_staff", False):
            return True
        if not isinstance(obj, DashboardTemplate):
            return False
        if obj.scope in (DashboardTemplate.Scope.GLOBAL, DashboardTemplate.Scope.FEATURE_FLAG):
            return False
        view_team_id = getattr(view, "team_id", None)
        if view_team_id is None:
            return False
        if obj.scope == DashboardTemplate.Scope.ONLY_TEAM and obj.team_id is not None and obj.team_id != view_team_id:
            return False
        return True


class DashboardTemplateSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = DashboardTemplate
        fields = [
            "id",
            "template_name",
            "dashboard_description",
            "dashboard_filters",
            "tags",
            "tiles",
            "variables",
            "deleted",
            "created_at",
            "created_by",
            "image_url",
            "team_id",
            "scope",
            "availability_contexts",
            "is_featured",
        ]

    def _handle_integrity_error(self, exc: IntegrityError) -> NoReturn:
        error_str = str(exc)
        if "unique_template_name_per_team" in error_str:
            raise ValidationError(
                detail="A dashboard template with this name already exists for this project.",
                code="unique_template_name_per_team",
            ) from exc
        raise exc

    def _request_user_is_staff(self) -> bool:
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        return bool(user and user.is_authenticated and user.is_staff)

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
                            k: ["Only name, description, tags, and delete can be changed for project templates."]
                            for k in sorted(forbidden_patch)
                        }
                    )

        if self.instance is None and not is_staff:
            requested_scope = attrs.get("scope") or initial.get("scope")
            if requested_scope not in (None, "", DashboardTemplate.Scope.ONLY_TEAM, "team"):
                raise ValidationError(
                    {"scope": ["Project templates must use team scope."]},
                )
            is_featured_val = initial.get("is_featured", attrs.get("is_featured"))
            if is_featured_val:
                raise ValidationError({"is_featured": ["Only staff can mark templates as featured."]})
            attrs["scope"] = DashboardTemplate.Scope.ONLY_TEAM
            attrs["is_featured"] = False
        return attrs

    def create(self, validated_data: dict, *args, **kwargs) -> DashboardTemplate:
        if not validated_data["tiles"]:
            raise ValidationError(detail="You need to provide tiles for the template.")

        # default scope is team
        if not validated_data.get("scope"):
            validated_data["scope"] = DashboardTemplate.Scope.ONLY_TEAM

        team_id = self.context["team_id"]
        validated_data["team_id"] = team_id
        org_id = Team.objects.filter(pk=team_id).values_list("organization_id", flat=True).first()
        if org_id is not None:
            enforce_organization_dashboard_template_limit(organization_id=cast(UUID, org_id))
        try:
            return super().create(validated_data, *args, **kwargs)
        except IntegrityError as exc:
            self._handle_integrity_error(exc)

    def update(self, instance: DashboardTemplate, validated_data: dict, *args, **kwargs) -> DashboardTemplate:
        will_restore = validated_data.get("deleted") is False and bool(instance.deleted)
        if will_restore and instance.team_id is not None:
            org_id = Team.objects.filter(pk=instance.team_id).values_list("organization_id", flat=True).first()
            if org_id is not None:
                enforce_organization_dashboard_template_limit(organization_id=cast(UUID, org_id))

        # Staff: global rows with no team become team-scoped to the project issuing the PATCH.
        if self._request_user_is_staff():
            scope_to = validated_data.get("scope")
            if (
                scope_to in (DashboardTemplate.Scope.ONLY_TEAM, "team")
                and instance.scope == DashboardTemplate.Scope.GLOBAL
                and instance.team_id is None
            ):
                context_team_id = self.context.get("team_id")
                if context_team_id is None:
                    raise ValidationError(detail="Cannot set team scope without a project context.")
                validated_data["team_id"] = context_team_id

        if not self._request_user_is_staff():
            validated_data.pop("scope", None)
            validated_data.pop("team_id", None)
            validated_data.pop("tiles", None)
            validated_data.pop("variables", None)
            validated_data.pop("dashboard_filters", None)
            validated_data.pop("is_featured", None)
            validated_data.pop("availability_contexts", None)
            validated_data.pop("image_url", None)
            validated_data.pop("github_url", None)

        try:
            return super().update(instance, validated_data, *args, **kwargs)
        except IntegrityError as exc:
            self._handle_integrity_error(exc)


class CopyDashboardTemplateSerializer(serializers.Serializer):
    source_template_id = serializers.UUIDField(
        help_text="UUID of a team-scoped template in the same organization. Global and feature-flag templates cannot be copied with this endpoint."
    )


def _iter_copy_name_candidates(base_name: str) -> Iterator[str]:
    yield base_name
    yield f"{base_name} (copy)"
    n = 2
    while True:
        yield f"{base_name} (copy {n})"
        n += 1


def _pick_unique_template_name_for_copy(*, team_id: int, base_name: str) -> str:
    """Resolves `template_name` collisions on the target team by suffixing `(copy)`, `(copy 2)`, …"""
    max_attempts = 50
    candidates = _iter_copy_name_candidates(base_name)
    for _ in range(max_attempts):
        name = next(candidates)
        if not DashboardTemplate.objects.filter(team_id=team_id, template_name=name).exists():
            return name
    raise ValidationError(
        detail="Could not find an available template name after multiple attempts. Rename the source template and try again.",
        code="template_name_exhausted",
    )


def _assert_user_can_read_source_for_copy(*, user: User, source_team: Team) -> None:
    if user.is_staff:
        return
    up = UserPermissions(user=user)
    if source_team.id not in up.team_ids_visible_for_user:
        raise NotFound()
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
                    "(`scope=team` rows for the current project). `feature_flag`: feature-flag dashboard templates only. "
                    "Omit for both official and this project's templates (default dashboard template picker behavior)."
                ),
                enum=["global", "team", "feature_flag"],
            ),
        ],
    ),
)
@extend_schema(tags=["core"])
class DashboardTemplateViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "dashboard_template"
    permission_classes = [CustomerDashboardTemplateWritePermission]
    serializer_class = DashboardTemplateSerializer
    queryset = DashboardTemplate.objects.all()

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        instance = serializer.save(created_by=user)
        if instance.scope != DashboardTemplate.Scope.GLOBAL and isinstance(user, User):
            report_user_action(
                user,
                "dashboard project template created",
                properties={
                    "template_id": str(instance.id),
                    "scope": instance.scope or "",
                    "team_id": instance.team_id,
                    "organization_id": self.organization_id,
                    "is_staff": bool(user.is_staff),
                    "created_by_id": instance.created_by_id,
                    "template_name": instance.template_name,
                    "tile_count": len(instance.tiles or []),
                    "variable_count": len(instance.variables or []),
                },
                team=self.team,
                organization=self.organization,
            )

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
        target_team_id = target_team.id
        target_org_id = cast(UUID, target_team.organization_id)

        source = DashboardTemplate.objects_including_soft_deleted.filter(id=source_template_id).first()
        if source is None or source.deleted:
            raise NotFound()

        if source.scope == DashboardTemplate.Scope.GLOBAL:
            raise ValidationError(
                {"source_template_id": ["Only project-scoped templates can be copied to another project."]}
            )
        if source.scope == DashboardTemplate.Scope.FEATURE_FLAG:
            raise ValidationError(
                {"source_template_id": ["Feature-flag templates cannot be copied with this endpoint."]}
            )
        if source.scope != DashboardTemplate.Scope.ONLY_TEAM or source.team_id is None:
            raise ValidationError(
                {"source_template_id": ["Only project-scoped templates can be copied to another project."]}
            )

        if source.team_id == target_team_id:
            raise ValidationError({"source_template_id": ["Source and destination must be different projects."]})

        source_team = Team.objects.filter(pk=source.team_id).first()
        if source_team is None:
            raise NotFound()
        if source_team.organization_id != target_org_id:
            raise NotFound()

        user = cast(User, request.user)
        _assert_user_can_read_source_for_copy(user=user, source_team=source_team)

        enforce_organization_dashboard_template_limit(organization_id=target_org_id)

        base_name = (source.template_name or "").strip() or "Untitled template"
        unique_name = _pick_unique_template_name_for_copy(team_id=target_team_id, base_name=base_name)

        new_instance = DashboardTemplate.objects.create(
            team_id=target_team_id,
            template_name=unique_name,
            dashboard_description=source.dashboard_description,
            # TODO(analytics-platform): dashboard_filters and variables are copied verbatim; both can embed
            # project-scoped references (e.g. cohort IDs in filter properties; variable defaults for events,
            # actions, or properties) that do not exist or differ on the target project. Tile queries have the
            # same class of issue. Consider validation and/or ID rewriting (cf. resource_transfer visitors).
            dashboard_filters=source.dashboard_filters,
            tiles=source.tiles or [],
            variables=source.variables,
            tags=source.tags or [],
            scope=DashboardTemplate.Scope.ONLY_TEAM,
            is_featured=False,
            image_url=None,
            github_url=None,
            availability_contexts=None,
            deleted=False,
            created_by=user if user.is_authenticated else None,
        )

        report_user_action(
            user,
            "dashboard project template copied between projects",
            properties={
                "source_template_id": str(source.id),
                "new_template_id": str(new_instance.id),
                "source_team_id": source.team_id,
                "target_team_id": target_team_id,
                "organization_id": str(self.organization_id),
                "template_name": unique_name,
                "tile_count": len(new_instance.tiles or []),
                "variable_count": len(new_instance.variables or []),
            },
            team=self.team,
            organization=self.organization,
        )

        serializer = DashboardTemplateSerializer(new_instance, context=self.get_serializer_context())
        return response.Response(serializer.data, status=status.HTTP_201_CREATED)

    def dangerously_get_queryset(self):
        # NOTE: we use the dangerous version as we want to bypass the team/org scoping and do it here instead depending on the scope
        filters = self.request.GET.dict()
        scope = filters.pop("scope", None)
        search = filters.pop("search", None)
        ordering = self.request.GET.get("ordering")

        # if scope is feature flag, then only return feature flag templates
        # they're implicitly global, so they are not associated with any teams
        if scope == DashboardTemplate.Scope.FEATURE_FLAG:
            query_condition = Q(scope=DashboardTemplate.Scope.FEATURE_FLAG)
        elif scope == DashboardTemplate.Scope.GLOBAL:
            query_condition = Q(scope=DashboardTemplate.Scope.GLOBAL)
        elif scope == DashboardTemplate.Scope.ONLY_TEAM:
            query_condition = Q(team_id=self.team_id) & Q(scope=DashboardTemplate.Scope.ONLY_TEAM)
        # otherwise we are in the new dashboard context so show global templates and ones from this team
        else:
            query_condition = Q(team_id=self.team_id) | Q(scope=DashboardTemplate.Scope.GLOBAL)

        # Include soft-deleted rows for retrieve/update so PATCH `{deleted: false}` (undo) can resolve the object.
        # The default manager excludes `deleted=True`, which made undo 404 after soft delete.
        qs = DashboardTemplate.objects_including_soft_deleted.filter(query_condition)

        is_featured_raw = self.request.query_params.get("is_featured")
        if is_featured_raw is not None:
            is_featured = str_to_bool(is_featured_raw)
            qs = qs.filter(is_featured=is_featured)
            # Feature-flag templates are tied to team_id but belong in `?scope=feature_flag` lists only;
            # featured carousels use `?is_featured=true` without that scope and must not surface them.
            if is_featured and scope != DashboardTemplate.Scope.FEATURE_FLAG:
                qs = qs.exclude(scope=DashboardTemplate.Scope.FEATURE_FLAG)

        # weighted full-text search
        if isinstance(search, str):
            qs = qs.annotate(
                rank=build_rank({"template_name": "A", "dashboard_description": "C", "tags": "B"}, search),
            )
            qs = qs.filter(rank__gt=0.05)
            qs = qs.order_by("-is_featured", "-rank", Lower("template_name"))
        else:
            qs = qs.order_by(*_dashboard_template_list_order_by(ordering))

        if self.action == "list":
            qs = qs.exclude(deleted=True)

        return qs
