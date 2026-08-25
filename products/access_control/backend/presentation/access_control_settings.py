"""The access control settings page's API.

AccessControlSettingsViewSetMixin belongs on the team and project viewsets only. It serves the
settings surface: project and per-tool defaults, per-member and per-role summaries and rules,
object search for the rule picker, and the generic object-rule write. The per-resource access
controls every product viewset mixes in stay in access_control.py.
"""

from collections import defaultdict
from dataclasses import asdict, dataclass
from functools import cache
from typing import TYPE_CHECKING, Any, cast

from django.apps import apps
from django.core.exceptions import (
    FieldDoesNotExist,
    ValidationError as DjangoValidationError,
)
from django.db.models import Model, Q
from django.db.models.functions import Coalesce
from django.urls import URLResolver, get_resolver

from rest_framework import exceptions
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.documentation import extend_schema
from posthog.exceptions_capture import capture_exception
from posthog.models import PropertyDefinition
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.scopes import INTERNAL_API_SCOPE_OBJECTS, APIScopeObject

from products.access_control.backend.facade.subject_access_control import SubjectAccessControl
from products.access_control.backend.facade.user_access_control import (
    ACCESS_CONTROL_LEVELS_RESOURCE,
    ACCESS_CONTROL_RESOURCES,
    AccessControlLevel,
    UserAccessControl,
    default_access_level,
    highest_access_level,
    minimum_access_level,
    ordered_access_levels,
)
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role

from .access_control import (
    AccessControlSerializer,
    AccessControlViewSetMixin,
    ResolvedAccessSerializer,
    upsert_access_control,
)

if TYPE_CHECKING:
    _GenericViewSet = GenericViewSet
else:
    _GenericViewSet = object


@dataclass(frozen=True, kw_only=True)
class _ResourceDisplayModel:
    app_label: str
    model_name: str
    name_field: str


# Names come from universal search's ENTITY_MAP first; these entries cover resources search doesn't
# index, so they have no ENTITY_MAP entry to borrow. Add one when a resource's objects render raw
# ids instead of names, in the rules list or the picker; delete one when search starts indexing the
# resource, since ENTITY_MAP is consulted first and the entry goes dead. A resource in neither place
# and with no derivable name field is left out of the picker and falls back to the raw id.
_MODELS_NOT_IN_ENTITY_MAP: dict[str, _ResourceDisplayModel] = {
    "evaluation": _ResourceDisplayModel(app_label="ai_observability", model_name="evaluation", name_field="name"),
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
    "ticket": _ResourceDisplayModel(app_label="conversations", model_name="ticket", name_field="ticket_number"),
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
        if resource == "ticket":
            # A bare number doesn't read as an object; match the ticket page's own title
            return {
                str(pk): _ResolvedObjectName(name=f"Ticket: {number}")
                for pk, number in rows.values_list("pk", "ticket_number")
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


def _project_entry(subject: SubjectAccessControl, team: Team) -> dict[str, Any]:
    """Project access is an object-level question (the team is the object), never resource-wide."""
    inherited = subject.inherited_access_for_object(team)
    return {
        "access_level": subject.stored_level("project", str(team.id)),
        "effective_access_level": subject.get_user_access_level(team),
        "inherited_access": ResolvedAccessSerializer(asdict(inherited)).data if inherited else None,
        "minimum": minimum_access_level("project"),
        "maximum": highest_access_level("project"),
    }


def _resource_entry(subject: SubjectAccessControl, resource: APIScopeObject) -> dict[str, Any]:
    effective = subject.access_level_for_resource(resource)
    inherited = subject.inherited_access_for_resource(resource)
    return {
        "access_level": subject.stored_level(resource, None),
        "effective_access_level": effective.access_level if effective else None,
        "inherited_access": ResolvedAccessSerializer(asdict(inherited)).data if inherited else None,
        "minimum": minimum_access_level(resource),
        "maximum": highest_access_level(resource),
    }


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
                "minimum": minimum_access_level(r),
                "maximum": highest_access_level(r),
            }
            for r in ACCESS_CONTROL_RESOURCES
        }

        # nosemgrep: api-response-must-match-schema -- unchanged response shape moved into the product boundary
        return Response(
            {
                "available_project_levels": list(ordered_access_levels("project")),
                "available_resource_levels": list(ACCESS_CONTROL_LEVELS_RESOURCE),
                "can_edit": user_access_control.check_can_modify_access_levels_for_object(team),
                "project_access_level": project_access_level,
                "resource_access_levels": resource_access_levels,
                # The resources the settings UI can search and rule on; every entry works with
                # access_control_object_search and access_control_object_rules. Levels ride along
                # per resource, like the per-resource access_controls endpoint returns them, so the
                # picker can only offer what a write would accept
                "object_rule_resources": [
                    {
                        "resource": r,
                        "available_access_levels": list(ordered_access_levels(r)),
                        "minimum_access_level": minimum_access_level(r),
                    }
                    for r in sorted(r for r in resources_with_object_access_controls() if _display_model(r) is not None)
                ],
            }
        )

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_roles")
    def access_control_roles(self, request: Request, *args, **kwargs):
        team = cast(Team, self.team)  # type: ignore
        user_access_control = cast(UserAccessControl, self.user_access_control)  # type: ignore

        roles = Role.objects.filter(organization=team.organization)
        # An optional role_id narrows the walk to one role, so the detail panel doesn't pay for the whole list
        if request.query_params.get("role_id"):
            roles = roles.filter(id=self._get_role(request, team).id)

        # The first subject loads the team's rules once; the rest are seeded from its pool
        team_rows = None

        results = []
        for role in roles:
            subject = SubjectAccessControl.for_role(user_access_control, team, str(role.id))
            subject.preload_access_controls(team_rows)
            if team_rows is None:
                team_rows = subject.team_access_controls
            results.append(
                {
                    "role_id": role.id,
                    "role_name": role.name,
                    "project": _project_entry(subject, team),
                    "resources": {
                        resource: _resource_entry(subject, resource) for resource in ACCESS_CONTROL_RESOURCES
                    },
                }
            )

        # nosemgrep: api-response-must-match-schema -- unchanged response shape moved into the product boundary
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

        # The first subject loads the team's rules once; the rest are seeded from its pool
        team_rows = None

        results = []
        for member in memberships:
            # role_memberships is prefetched on the queryset, so seeding from it costs no query
            role_ids = [str(rm.role_id) for rm in member.role_memberships.all()]
            subject = SubjectAccessControl.for_member(user_access_control, team, member)
            subject.preload_access_controls(team_rows, subject_role_ids=role_ids)
            if team_rows is None:
                team_rows = subject.team_access_controls

            # When the org restricts member list visibility, project members only see users with
            # project-scoped access (explicit grant, role, or default) — org admins aren't implied in
            if hide_non_project_members and not subject.has_project_scoped_access(team):
                continue

            user = member.user
            results.append(
                {
                    "organization_membership_id": member.id,
                    "user": {
                        "uuid": user.uuid,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "email": user.email,
                    },
                    "organization_level": member.level,
                    "project": _project_entry(subject, team),
                    "resources": {
                        resource: _resource_entry(subject, resource) for resource in ACCESS_CONTROL_RESOURCES
                    },
                }
            )

        # nosemgrep: api-response-must-match-schema -- unchanged response shape moved into the product boundary
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
        user_access_control = cast(UserAccessControl, self.user_access_control)  # type: ignore
        # An org hiding its member list means plain members can't browse other members' details, so 404.
        # Org admins and explicit project admins keep these endpoints, since they can manage access
        # and open details from the members list.
        if (
            not team.organization.members_can_see_org_members
            and not user_access_control.check_can_modify_access_levels_for_object(team)
        ):
            raise exceptions.NotFound()
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
        # Names resolve for every rule, including objects the caller cannot access themselves:
        # rules lists show what is configured, while the picker search and the rule write are the
        # surfaces that hide inaccessible objects
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
            for pd in PropertyDefinition.objects.filter(
                team_id=team.id, id__in=[rule.property_definition_id for rule in rules]
            )
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
        # Objects mid-deletion or never saved are not sensible rule targets. Excluding rather than
        # filtering keeps rows whose `deleted` is NULL, which is every row on models where the field
        # was added without a default (session recordings), and legacy rows elsewhere
        if _model_has_field(display.model, "deleted"):
            qs = qs.exclude(deleted=True)
        # Insight-specific rather than probing for a `saved` field: only Insight has one among the
        # picker resources, and a future model's field of that name could mean something else
        if resource == "insight":
            qs = qs.filter(saved=True)

        # Enough options for a dropdown; the search narrows, and a pasted URL selects exactly one
        limit = 20
        try:
            if resource == "insight":
                if lookup:
                    qs = qs.filter(pk=lookup) if lookup.isdigit() else qs.filter(short_id=lookup)
                elif search:
                    qs = qs.filter(Q(name__icontains=search) | Q(derived_name__icontains=search))
                # Order by what the labels show: name falls back to derived_name, and sorting on
                # name alone would push derived-name-only insights behind every named match
                pks = [
                    str(pk) for pk in qs.order_by(Coalesce("name", "derived_name")).values_list("pk", flat=True)[:limit]
                ]
            else:
                if lookup:
                    qs = qs.filter(pk=lookup)
                elif search:
                    # name_field comes from _display_model's code-defined maps, never from the
                    # request, and search is only a value
                    # nosemgrep: orm-field-injection, no-request-param-orm-filter
                    qs = qs.filter(**{f"{display.name_field}__icontains": search})
                pks = [str(pk) for pk in qs.order_by(display.name_field).values_list("pk", flat=True)[:limit]]
        except (ValueError, DjangoValidationError):
            # A lookup id of the wrong shape for the model's pk matches nothing
            pks = []
        # One place builds display names, so the picker shows exactly what the rules list will
        names = _resolve_object_names(resource, pks, team.id)
        results = [{"id": pk, "name": (resolved.name if (resolved := names.get(pk)) else None) or pk} for pk in pks]
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
        return upsert_access_control(
            team=team,
            user_access_control=user_access_control,
            build_serializer=lambda instance: AccessControlSerializer(instance, data=data, context=context),
        )
