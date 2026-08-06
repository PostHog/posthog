"""The access control settings page's API.

AccessControlSettingsViewSetMixin belongs on the team and project viewsets only. It serves the
settings surface: project and per-tool defaults, per-member and per-role summaries and rules,
object search for the rule picker, and the generic object-rule write. The per-resource access
controls every product viewset mixes in stay in access_control.py.
"""

from collections import defaultdict
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any, cast

from django.apps import apps
from django.core.exceptions import (
    FieldDoesNotExist,
    ValidationError as DjangoValidationError,
)
from django.db.models import Model, Q
from django.urls import URLResolver, get_resolver

from rest_framework import exceptions, status
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.documentation import extend_schema
from posthog.constants import AvailableFeature
from posthog.exceptions_capture import capture_exception
from posthog.models import PropertyDefinition
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.rbac.user_access_control import (
    ACCESS_CONTROL_LEVELS_RESOURCE,
    ACCESS_CONTROL_RESOURCES,
    AccessControlLevel,
    UserAccessControl,
    default_access_level,
    get_effective_access_level_for_member,
    get_effective_access_level_for_role,
    highest_access_level,
    minimum_access_level,
    ordered_access_levels,
)
from posthog.scopes import INTERNAL_API_SCOPE_OBJECTS, APIScopeObject

from ee.api.rbac.access_control import AccessControlSerializer, AccessControlViewSetMixin
from ee.models.rbac.access_control import AccessControl
from ee.models.rbac.role import Role

if TYPE_CHECKING:
    _GenericViewSet = GenericViewSet
else:
    _GenericViewSet = object


@dataclass(frozen=True, kw_only=True)
class _ResourceDisplayModel:
    app_label: str
    model_name: str
    name_field: str


# Used only by _resolve_object_names below, which turns a rule's resource_id into a display name.
# Names come from universal search's ENTITY_MAP first; these entries cover resources search doesn't
# index, so they have no ENTITY_MAP entry to borrow. Add one when a resource's rules render raw ids
# instead of names; delete one when search starts indexing the resource, since ENTITY_MAP is
# consulted first and the entry goes dead. Resources in neither place fall back to the raw id.
_MODELS_NOT_IN_ENTITY_MAP: dict[str, _ResourceDisplayModel] = {
    "warehouse_view": _ResourceDisplayModel(
        app_label="data_modeling", model_name="datawarehousesavedquery", name_field="name"
    ),
    "warehouse_table": _ResourceDisplayModel(
        app_label="warehouse_sources", model_name="datawarehousetable", name_field="name"
    ),
    "external_data_source": _ResourceDisplayModel(
        app_label="warehouse_sources", model_name="externaldatasource", name_field="source_type"
    ),
    "session_recording": _ResourceDisplayModel(
        app_label="posthog", model_name="sessionrecording", name_field="session_id"
    ),
}


@dataclass(frozen=True, kw_only=True)
class _ResolvedObjectName:
    name: str | None
    # Insights link by short_id rather than pk, so the frontend needs it alongside the name
    short_id: str | None = None


def _resolve_object_names(resource: str, resource_ids: list[str], team_id: int) -> dict[str, _ResolvedObjectName]:
    """Map {resource_id -> display info} for one resource type, empty when we can't name its objects.

    Queries through _base_manager so rules pointing at soft-deleted objects still resolve: those are
    exactly the rows someone opens this page to clean up. Tenant isolation holds via team_id.
    """
    display = _display_model(resource) if resource_ids else None
    if display is None:
        return {}
    try:
        rows = display.model._base_manager.filter(team_id=team_id, pk__in=resource_ids)
        if resource == "insight":
            # Insight.name is nullable and saved insights often carry only derived_name, and insight
            # URLs address short_ids rather than the pk rules store
            return {
                str(pk): _ResolvedObjectName(name=name or derived_name, short_id=short_id)
                for pk, name, derived_name, short_id in rows.values_list("pk", "name", "derived_name", "short_id")
            }
        return {str(pk): _ResolvedObjectName(name=name) for pk, name in rows.values_list("pk", display.name_field)}
    except Exception as e:
        # A resource_id of the wrong shape for the model's pk, or a model that moved. The rules list
        # falls back to raw ids, but report it: one failure usually breaks the whole resource type
        capture_exception(e, {"resource": resource})
        return {}


@cache
def resources_with_object_access_controls() -> dict[APIScopeObject, frozenset[type[Model]]]:
    """Resources that support object-level access controls, mapped to the models behind them.

    A viewset opts in by mixing in AccessControlViewSetMixin, so the registered routes are the
    source of truth and this cannot drift from the code; adding the mixin also puts the resource in
    the settings picker. A scope served by several viewsets maps to several models. The snapshot
    test in test_access_control.py records the resources; regenerate it with `pytest
    --snapshot-update`.
    """
    found: dict[APIScopeObject, set[type[Model]]] = {}

    def walk(resolver: URLResolver) -> None:
        for pattern in resolver.url_patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern)
                continue
            cls = getattr(pattern.callback, "cls", None)
            if cls is None or not issubclass(cls, AccessControlViewSetMixin):
                continue
            scope = getattr(cls, "scope_object", None)
            # Project-level access is its own control (the "Project access" dropdown), never an
            # object rule; every rules endpoint filters resource="project" out as well
            if scope and scope != "INTERNAL" and scope != "project" and scope not in INTERNAL_API_SCOPE_OBJECTS:
                queryset = getattr(cls, "queryset", None)
                found.setdefault(scope, set())
                if queryset is not None:
                    found[scope].add(queryset.model)

    walk(get_resolver())
    return {scope: frozenset(models) for scope, models in found.items()}


def _model_has_field(model: type[Model], field: str) -> bool:
    try:
        model._meta.get_field(field)
        return True
    except FieldDoesNotExist:
        return False


@dataclass(frozen=True, kw_only=True)
class _DisplayModel:
    """Where a resource's objects live and which field names them."""

    model: type[Model]
    name_field: str


def _display_model(resource: str) -> _DisplayModel | None:
    """Resolve a resource to its model and display field. None means the settings UI cannot work
    with the resource's objects: search returns 400, rule writes return 400, existing rules show
    raw ids.

    A resource qualifies when its viewsets carry object-level access controls and we can name its
    objects, tried in order: search's ENTITY_MAP (its rank-A field is the display name), the
    supplement for resources search doesn't index, and finally a resource whose routes expose
    exactly one model carrying a recognizable name field.
    """
    # Gate before the cached resolver: resource is raw request input, and caching unknown values
    # would grow the cache by one permanent entry per distinct garbage string
    if resource not in resources_with_object_access_controls():
        return None
    return _display_model_for_known_resource(resource)


@cache
def _display_model_for_known_resource(resource: str) -> _DisplayModel | None:
    from posthog.api.search import (
        ENTITY_MAP,  # noqa: PLC0415 — imports every searchable product model, keep it off this module's import path
    )

    model: type[Model] | None = None
    name_field: str | None = None
    entity = ENTITY_MAP.get(resource)
    supplement = _MODELS_NOT_IN_ENTITY_MAP.get(resource)
    if entity is not None:
        model = entity["klass"]
        name_field = next((field for field, rank in entity["search_fields"].items() if rank == "A"), None)
    elif supplement is not None:
        model = apps.get_model(supplement.app_label, supplement.model_name)
        name_field = supplement.name_field
    else:
        models = resources_with_object_access_controls().get(cast(APIScopeObject, resource)) or frozenset()
        if len(models) == 1:
            model = next(iter(models))
            name_field = next((field for field in ("name", "title", "key") if _model_has_field(model, field)), None)

    if model is None or name_field is None or not _model_has_field(model, "team"):
        return None
    return _DisplayModel(model=model, name_field=name_field)


@dataclass(frozen=True, kw_only=True)
class _ObjectRuleValidationContext:
    """Duck-typed stand-in for the view in AccessControlSerializer's context, so the generic
    object-rule endpoint runs exactly the validation the per-resource access_controls actions run."""

    team: Team
    user_access_control: UserAccessControl
    target: Model

    def get_object(self) -> Model:
        return self.target


class AccessControlSettingsViewSetMixin(_GenericViewSet):
    """Actions for the access control settings page, addressed as /api/projects/:id/... only."""

    def dangerously_get_required_scopes(self, request, view) -> list[str] | None:
        """GET settings endpoints require access_control:read; other actions defer along the MRO."""
        if request.method == "GET" and self.action in [
            "access_control_defaults",
            "access_control_roles",
            "access_control_members",
            "access_control_default_objects",
            "access_control_default_properties",
            "access_control_member_objects",
            "access_control_member_properties",
            "access_control_role_objects",
            "access_control_role_properties",
            "access_control_object_search",
        ]:
            return ["access_control:read"]
        if request.method == "PUT" and self.action == "access_control_object_rules":
            return ["access_control:write"]
        parent = getattr(super(), "dangerously_get_required_scopes", None)
        return parent(request, view) if parent is not None else None

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_defaults")
    def access_control_defaults(self, request: Request, *args, **kwargs):
        team = cast(Team, self.team)  # type: ignore
        user_access_control = cast(UserAccessControl, self.user_access_control)  # type: ignore

        default_access_controls = AccessControl.objects.filter(team=team, organization_member=None, role=None)

        project_access_level: AccessControlLevel = default_access_level("project")
        saved_resource_levels: dict[str, str] = {}

        for ac in default_access_controls:
            if ac.resource == "project":
                project_access_level = ac.access_level
            elif ac.resource_id is None and ac.resource in set(ACCESS_CONTROL_RESOURCES):
                saved_resource_levels[ac.resource] = ac.access_level

        resource_access_levels = {
            r: {
                "access_level": saved_resource_levels.get(r),
                # What applies when no rule exists anywhere, so the UI can spell out the fallback
                "system_default_access_level": default_access_level(r),
                "minimum": minimum_access_level(r),
                "maximum": highest_access_level(r),
            }
            for r in ACCESS_CONTROL_RESOURCES
        }

        return Response(
            {
                "available_project_levels": list(ordered_access_levels("project")),
                "available_resource_levels": list(ACCESS_CONTROL_LEVELS_RESOURCE),
                "can_edit": user_access_control.check_can_modify_access_levels_for_object(team),
                "project_access_level": project_access_level,
                "resource_access_levels": resource_access_levels,
                # The resources the settings UI can search and rule on; every entry works with
                # access_control_object_search and access_control_object_rules
                "object_rule_resources": sorted(
                    r for r in resources_with_object_access_controls() if _display_model(r) is not None
                ),
            }
        )

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_roles")
    def access_control_roles(self, request: Request, *args, **kwargs):
        team = cast(Team, self.team)  # type: ignore
        user_access_control = cast(UserAccessControl, self.user_access_control)  # type: ignore

        access_controls = AccessControl.objects.filter(team=team).filter(Q(resource="project") | Q(resource_id=None))

        # Build lookup dicts from saved access controls
        project_default_level: AccessControlLevel = default_access_level("project")
        resource_default_levels: dict[APIScopeObject, AccessControlLevel] = {}
        role_project_overrides: dict[str, AccessControlLevel] = {}
        role_resource_overrides: dict[tuple[str, APIScopeObject], AccessControlLevel] = {}

        for ac in access_controls:
            level: AccessControlLevel = ac.access_level
            resource_type: APIScopeObject = ac.resource
            role_id = ac.role_id
            is_default = ac.organization_member_id is None and role_id is None

            if is_default:
                if ac.resource == "project":
                    project_default_level = level
                else:
                    resource_default_levels[resource_type] = level
            elif role_id:
                if ac.resource == "project":
                    role_project_overrides[str(role_id)] = level
                else:
                    role_resource_overrides[(str(role_id), resource_type)] = level

        # Role overrides (project- and resource-level) only take effect if the
        # organization has the ROLE_BASED_ACCESS feature; otherwise role rows in the
        # DB are inert and we must not surface them as the effective access level.
        role_based_access_supported = team.organization.is_feature_available(AvailableFeature.ROLE_BASED_ACCESS)

        # Build results for each role
        roles = Role.objects.filter(organization=team.organization)
        # An optional role_id narrows the walk to one role, so the detail panel doesn't pay for the whole list
        if request.query_params.get("role_id"):
            roles = roles.filter(id=self._get_role(request, team).id)
        results = []

        for role in roles:
            rid = str(role.id)

            project_role_level = role_project_overrides.get(rid) if role_based_access_supported else None
            project_result = get_effective_access_level_for_role(
                resource="project",
                default_level=project_default_level,
                role_level=project_role_level,
            )

            resource_entries: dict[str, dict] = {}
            for resource in ACCESS_CONTROL_RESOURCES:
                resource_role_level = (
                    role_resource_overrides.get((rid, resource)) if role_based_access_supported else None
                )
                resource_default = resource_default_levels.get(resource)
                resource_result = get_effective_access_level_for_role(
                    resource=resource,
                    default_level=resource_default,
                    role_level=resource_role_level,
                )
                resource_entries[resource] = {
                    "access_level": resource_role_level,
                    "effective_access_level": resource_result.effective_access_level,
                    "inherited_access_level": resource_result.inherited_access_level,
                    "inherited_access_level_reason": resource_result.inherited_access_level_reason,
                    "minimum": minimum_access_level(resource),
                    "maximum": highest_access_level(resource),
                }

            results.append(
                {
                    "role_id": role.id,
                    "role_name": role.name,
                    "project": {
                        "access_level": project_role_level,
                        "effective_access_level": project_result.effective_access_level,
                        "inherited_access_level": project_result.inherited_access_level,
                        "inherited_access_level_reason": project_result.inherited_access_level_reason,
                        "minimum": minimum_access_level("project"),
                        "maximum": highest_access_level("project"),
                    },
                    "resources": resource_entries,
                }
            )

        return Response(
            {
                "available_project_levels": list(ordered_access_levels("project")),
                "available_resource_levels": list(ACCESS_CONTROL_LEVELS_RESOURCE),
                "can_edit": user_access_control.check_can_modify_access_levels_for_object(team),
                "results": results,
            }
        )

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_members")
    def access_control_members(self, request: Request, *args, **kwargs):
        team = cast(Team, self.team)  # type: ignore
        user_access_control = cast(UserAccessControl, self.user_access_control)  # type: ignore

        access_controls = AccessControl.objects.filter(team=team).filter(Q(resource="project") | Q(resource_id=None))

        # Build lookup dicts from saved access controls
        project_default_level: AccessControlLevel = default_access_level("project")
        resource_default_levels: dict[APIScopeObject, AccessControlLevel] = {}
        role_project_overrides: dict[str, AccessControlLevel] = {}
        role_resource_overrides: dict[tuple[str, APIScopeObject], AccessControlLevel] = {}
        member_project_overrides: dict[str, AccessControlLevel] = {}
        member_resource_overrides: dict[tuple[str, APIScopeObject], AccessControlLevel] = {}

        for ac in access_controls:
            level: AccessControlLevel = ac.access_level
            resource_type: APIScopeObject = ac.resource
            role_id = ac.role_id
            member_id = ac.organization_member_id
            is_default = member_id is None and role_id is None

            if is_default:
                if ac.resource == "project":
                    project_default_level = level
                else:
                    resource_default_levels[resource_type] = level
            elif role_id:
                if ac.resource == "project":
                    role_project_overrides[str(role_id)] = level
                else:
                    role_resource_overrides[(str(role_id), resource_type)] = level
            elif member_id:
                if ac.resource == "project":
                    member_project_overrides[str(member_id)] = level
                else:
                    member_resource_overrides[(str(member_id), resource_type)] = level

        # Role overrides (project- and resource-level) only take effect if the
        # organization has the ROLE_BASED_ACCESS feature; otherwise role rows in the
        # DB are inert and we must not let them influence members' effective access.
        role_based_access_supported = team.organization.is_feature_available(AvailableFeature.ROLE_BASED_ACCESS)

        # Build results for each member
        memberships = (
            OrganizationMembership.objects.filter(organization=team.organization, user__is_active=True)
            .select_related("user")
            .prefetch_related("role_memberships")
        )
        # An optional member_id narrows the walk to one member, so the detail panel doesn't pay for the whole list
        if request.query_params.get("member_id"):
            memberships = memberships.filter(id=self._get_membership(request, team).id)

        can_edit = user_access_control.check_can_modify_access_levels_for_object(team)
        hide_non_project_members = (
            not team.organization.members_can_see_org_members and not user_access_control.is_organization_admin
        )

        results = []
        for membership in memberships:
            mid = str(membership.id)
            is_org_admin = membership.level >= OrganizationMembership.Level.ADMIN
            # Role memberships only contribute when ROLE_BASED_ACCESS is enabled.
            member_role_ids = (
                [str(rm.role_id) for rm in membership.role_memberships.all()] if role_based_access_supported else []
            )

            project_member_level = member_project_overrides.get(mid)
            project_role_levels: list[AccessControlLevel] = [
                role_project_overrides[rid] for rid in member_role_ids if rid in role_project_overrides
            ]
            project_result = get_effective_access_level_for_member(
                resource="project",
                default_level=project_default_level,
                role_levels=project_role_levels,
                member_level=project_member_level,
                is_org_admin=is_org_admin,
            )

            # When the org restricts member list visibility, project members only see users with
            # project-scoped access (explicit grant, role, or default) — org admins aren't implied in
            if hide_non_project_members:
                project_scoped_result = get_effective_access_level_for_member(
                    resource="project",
                    default_level=project_default_level,
                    role_levels=project_role_levels,
                    member_level=project_member_level,
                    is_org_admin=False,
                )
                if project_scoped_result.effective_access_level in (None, "none"):
                    continue

            resource_entries: dict[str, dict] = {}
            for resource in ACCESS_CONTROL_RESOURCES:
                resource_member_level = member_resource_overrides.get((mid, resource))
                resource_default = resource_default_levels.get(resource)
                resource_role_levels: list[AccessControlLevel] = [
                    role_resource_overrides[(rid, resource)]
                    for rid in member_role_ids
                    if (rid, resource) in role_resource_overrides
                ]
                resource_result = get_effective_access_level_for_member(
                    resource=resource,
                    default_level=resource_default,
                    role_levels=resource_role_levels,
                    member_level=resource_member_level,
                    is_org_admin=is_org_admin,
                )
                resource_entries[resource] = {
                    "access_level": resource_member_level,
                    "effective_access_level": resource_result.effective_access_level,
                    "inherited_access_level": resource_result.inherited_access_level,
                    "inherited_access_level_reason": resource_result.inherited_access_level_reason,
                    "minimum": minimum_access_level(resource),
                    "maximum": highest_access_level(resource),
                }

            user = membership.user
            results.append(
                {
                    "organization_membership_id": membership.id,
                    "user": {
                        "uuid": user.uuid,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "email": user.email,
                    },
                    "organization_level": membership.level,
                    "project": {
                        "access_level": project_member_level,
                        "effective_access_level": project_result.effective_access_level,
                        "inherited_access_level": project_result.inherited_access_level,
                        "inherited_access_level_reason": project_result.inherited_access_level_reason,
                        "minimum": minimum_access_level("project"),
                        "maximum": highest_access_level("project"),
                    },
                    "resources": resource_entries,
                }
            )

        return Response(
            {
                "available_project_levels": list(ordered_access_levels("project")),
                "available_resource_levels": list(ACCESS_CONTROL_LEVELS_RESOURCE),
                "can_edit": can_edit,
                "results": results,
            }
        )

    def _get_membership(self, request: Request, team: Team) -> OrganizationMembership:
        member_id = request.query_params.get("member_id")
        if not member_id:
            raise exceptions.ValidationError("member_id is required")
        return get_object_or_404(OrganizationMembership, id=member_id, organization=team.organization)

    def _get_role(self, request: Request, team: Team) -> Role:
        role_id = request.query_params.get("role_id")
        if not role_id:
            raise exceptions.ValidationError("role_id is required")
        return get_object_or_404(Role, id=role_id, organization=team.organization)

    def _object_rules_response(
        self,
        team: Team,
        *,
        membership: OrganizationMembership | None = None,
        role: Role | None = None,
    ) -> Response:
        """Object-level rules belonging to one subject: a member, a role, or the project itself.

        Passing neither a member nor a role targets the project-wide rules, the ones that apply to
        everyone without a rule of their own.

        Deliberately returns only the subject's own rules, without resolving what would apply in
        their absence — object-level resolution differs between code paths today (explicit-wins vs
        max), so surfacing a computed fallback here would be wrong in edge cases. Revisit once
        resolution returns the level together with its source.
        """
        rule_filter: dict[str, Any]
        if membership is not None:
            rule_filter = {"organization_member": membership}
        elif role is not None:
            rule_filter = {"role": role}
        else:
            # Project-wide rules are the rows with no subject at all
            rule_filter = {"organization_member": None, "role": None}
        rows = list(
            AccessControl.objects.filter(team=team, resource_id__isnull=False, **rule_filter).exclude(
                resource="project"
            )
        )
        if not rows:
            return Response({"results": []})

        ids_by_resource: dict[str, list[str]] = defaultdict(list)
        for ac in rows:
            ids_by_resource[ac.resource].append(ac.resource_id)
        names_by_resource = {
            resource: _resolve_object_names(resource, ids, team.id) for resource, ids in ids_by_resource.items()
        }

        results = []
        for ac in rows:
            resolved = names_by_resource.get(ac.resource, {}).get(str(ac.resource_id))
            results.append(
                {
                    "resource": ac.resource,
                    "resource_id": ac.resource_id,
                    "name": (resolved.name if resolved else None) or ac.resource_id,
                    "short_id": resolved.short_id if resolved else None,
                    "access_level": ac.access_level,
                }
            )
        results.sort(key=lambda r: (r["resource"], (r["name"] or "").lower()))
        return Response({"results": results})

    def _property_rules_response(
        self,
        team: Team,
        *,
        organization_member: OrganizationMembership | None = None,
        role: Role | None = None,
    ) -> Response:
        """Property rules belonging to one subject, including read & write grants over a stricter default."""
        from products.access_control.backend.facade.api import (
            list_property_access_controls,  # noqa: PLC0415 — the facade imports ee models, a module-level import would be circular
        )

        rules = list_property_access_controls(
            team_id=team.id,
            organization_member_id=organization_member.id if organization_member else None,
            role_id=role.id if role else None,
        )
        definitions_by_id = {
            str(pd.id): pd
            for pd in PropertyDefinition.objects.filter(id__in=[rule.property_definition_id for rule in rules])
        }

        results = []
        for rule in rules:
            pd = definitions_by_id.get(str(rule.property_definition_id))
            if pd is None:
                continue
            results.append(
                {
                    "property_definition_id": str(pd.id),
                    "property": pd.name,
                    "property_type": "person" if pd.type == pd.Type.PERSON else "event",
                    "access_level": rule.access_level.value,
                }
            )
        results.sort(key=lambda r: (r["property_type"], (r["property"] or "").lower()))
        return Response({"results": results})

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_default_objects")
    def access_control_default_objects(self, request: Request, *args, **kwargs) -> Response:
        """Object-level access rules that apply to everyone without a rule of their own."""
        team = cast(Team, self.team)  # type: ignore
        return self._object_rules_response(team)

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_default_properties")
    def access_control_default_properties(self, request: Request, *args, **kwargs) -> Response:
        """Property restrictions that apply to everyone without a rule of their own."""
        team = cast(Team, self.team)  # type: ignore
        return self._property_rules_response(team)

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_member_objects")
    def access_control_member_objects(self, request: Request, *args, **kwargs) -> Response:
        """Object-level access rules configured for a member."""
        team = cast(Team, self.team)  # type: ignore
        membership = self._get_membership(request, team)
        return self._object_rules_response(team, membership=membership)

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_member_properties")
    def access_control_member_properties(self, request: Request, *args, **kwargs) -> Response:
        """Property restrictions configured for a member."""
        team = cast(Team, self.team)  # type: ignore
        membership = self._get_membership(request, team)
        return self._property_rules_response(team, organization_member=membership)

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_role_objects")
    def access_control_role_objects(self, request: Request, *args, **kwargs) -> Response:
        """Object-level access rules configured for a role."""
        team = cast(Team, self.team)  # type: ignore
        role = self._get_role(request, team)
        return self._object_rules_response(team, role=role)

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_role_properties")
    def access_control_role_properties(self, request: Request, *args, **kwargs) -> Response:
        """Property restrictions configured for a role."""
        team = cast(Team, self.team)  # type: ignore
        role = self._get_role(request, team)
        return self._property_rules_response(team, role=role)

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_object_search")
    def access_control_object_search(self, request: Request, *args, **kwargs) -> Response:
        """Searches objects of one resource type: `?resource=` plus `?search=` by name or `?id=` exact.

        Works for every resource the defaults endpoint lists in object_rule_resources, with the same
        display names the rules list shows. Returns pks, the identifier stored on rules and taken by
        access_control_object_rules; `?id=` also accepts an insight short_id, since insight URLs
        carry those.
        """
        team = cast(Team, self.team)  # type: ignore
        user_access_control = cast(UserAccessControl, self.user_access_control)  # type: ignore
        resource = request.query_params.get("resource") or ""
        display = _display_model(resource)
        if display is None:
            raise exceptions.ValidationError("resource does not support object access rules")

        search = request.query_params.get("search") or ""
        lookup = request.query_params.get("id") or ""
        qs = display.model._default_manager.filter(team_id=team.id)
        # Objects the requester cannot see are not theirs to find or configure. Org admins see
        # everything, matching how they can already configure access anywhere
        qs = user_access_control.filter_queryset_by_access_level(
            qs, include_all_if_admin=True, resource=cast(APIScopeObject, resource)
        )
        # Objects mid-deletion or never saved are not sensible rule targets
        if _model_has_field(display.model, "deleted"):
            qs = qs.filter(deleted=False)
        if _model_has_field(display.model, "saved"):
            qs = qs.filter(saved=True)

        # Enough options for a dropdown; the search narrows, and a pasted URL selects exactly one
        limit = 20
        try:
            if resource == "insight":
                if lookup:
                    qs = qs.filter(pk=lookup) if lookup.isdigit() else qs.filter(short_id=lookup)
                elif search:
                    qs = qs.filter(Q(name__icontains=search) | Q(derived_name__icontains=search))
                rows = qs.order_by("name").values_list("pk", "name", "derived_name")[:limit]
                results = [{"id": str(pk), "name": name or derived_name or str(pk)} for pk, name, derived_name in rows]
            else:
                if lookup:
                    qs = qs.filter(pk=lookup)
                elif search:
                    qs = qs.filter(**{f"{display.name_field}__icontains": search})
                rows = qs.order_by(display.name_field).values_list("pk", display.name_field)[:limit]
                results = [{"id": str(pk), "name": str(name) if name else str(pk)} for pk, name in rows]
        except (ValueError, DjangoValidationError):
            # A lookup id of the wrong shape for the model's pk matches nothing
            results = []
        return Response({"results": results})

    @extend_schema(exclude=True)
    @action(methods=["PUT"], detail=True, url_path="access_control_object_rules")
    def access_control_object_rules(self, request: Request, *args, **kwargs) -> Response:
        """Create, update or clear one object rule, addressing the object by resource + pk.

        The per-resource access_controls actions address objects by each viewset's lookup - a
        notebook's short_id, for example - while rules and the options search use pks, so the
        settings UI writes here. Validation and permission checks are AccessControlSerializer's,
        identical to the per-resource path.
        """
        team = cast(Team, self.team)  # type: ignore
        user_access_control = cast(UserAccessControl, self.user_access_control)  # type: ignore

        resource = str(request.data.get("resource") or "")
        resource_id = str(request.data.get("resource_id") or "")
        display = _display_model(resource)
        if display is None:
            raise exceptions.ValidationError("resource does not support object access rules")
        if not resource_id:
            raise exceptions.ValidationError("resource_id is required")
        visible = user_access_control.filter_queryset_by_access_level(
            display.model._default_manager.filter(team_id=team.id),
            include_all_if_admin=True,
            resource=cast(APIScopeObject, resource),
        )
        # An object the requester cannot see is not theirs to configure; 404 rather than 403 so the
        # endpoint doesn't confirm it exists
        target = get_object_or_404(visible, pk=resource_id)

        data = {**request.data, "resource": resource, "resource_id": resource_id}
        context = {
            **self.get_serializer_context(),
            "view": _ObjectRuleValidationContext(team=team, user_access_control=user_access_control, target=target),
        }
        serializer = AccessControlSerializer(data=data, context=context)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data

        instance = AccessControl.objects.filter(
            team=team,
            resource=resource,
            resource_id=resource_id,
            organization_member=params.get("organization_member"),
            role=params.get("role"),
        ).first()

        if params["access_level"] is None:
            if instance:
                instance.delete()
                user_access_control._clear_cache()
            return Response(status=status.HTTP_204_NO_CONTENT)

        if instance:
            serializer = AccessControlSerializer(instance, data=data, context=context)
            serializer.is_valid(raise_exception=True)
        serializer.validated_data["team"] = team
        serializer.save()
        user_access_control._clear_cache()
        return Response(serializer.data, status=status.HTTP_200_OK)
