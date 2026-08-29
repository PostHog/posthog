import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from enum import Enum
from functools import cache, cached_property
from typing import TYPE_CHECKING, Any, Literal, Optional, cast, get_args

from django.db.models import Case, CharField, Exists, F, ForeignKey, Model, OuterRef, Q, QuerySet, Value, When
from django.db.models.functions import Cast

import posthoganalytics
from opentelemetry import trace

from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.scopes import API_SCOPE_OBJECTS, INTERNAL_API_SCOPE_OBJECTS, APIScopeObject
from posthog.settings import EE_AVAILABLE

if TYPE_CHECKING:
    from posthog.models.file_system.file_system import FileSystem
    from posthog.user_permissions import UserPermissions

    from products.access_control.backend.models.access_control import AccessControl

    _AccessControl = AccessControl
else:
    _AccessControl = object


from products.access_control.backend.models.access_control import AccessControl


class AccessSource(Enum):
    """Enum for how a user got access to a resource"""

    CREATOR = "creator"
    ORGANIZATION_ADMIN = "organization_admin"
    EXPLICIT_MEMBER = "explicit_member"
    EXPLICIT_ROLE = "explicit_role"
    PROJECT_ADMIN = "project_admin"
    DEFAULT = "default"


AccessControlLevelNone = Literal["none"]
AccessControlLevelMember = Literal[AccessControlLevelNone, "member", "admin"]
AccessControlLevelResource = Literal[AccessControlLevelNone, "viewer", "editor", "manager"]
AccessControlLevel = Literal[AccessControlLevelMember, AccessControlLevelResource]

NO_ACCESS_LEVEL = "none"
ACCESS_CONTROL_LEVELS_MEMBER: tuple[AccessControlLevelMember, ...] = get_args(AccessControlLevelMember)
ACCESS_CONTROL_LEVELS_RESOURCE: tuple[AccessControlLevelResource, ...] = get_args(AccessControlLevelResource)

# We need to restrict this for HogQL access control which uses `NOT IN (...)`
ACCESS_CONTROL_MAX_OBJECTS_PER_RESOURCE = 1000

ACCESS_CONTROL_RESOURCES: tuple[APIScopeObject, ...] = (
    "action",
    "customer_analytics",
    "dashboard",
    "early_access_feature",
    "endpoint",
    "experiment",
    "export",
    "external_data_source",
    "warehouse_objects",
    "feature_flag",
    "heatmap",
    "hog_flow",
    "insight",
    "llm_analytics",
    "evaluation",
    "tagger",
    "llm_skill",
    "ai_observability_clusters",
    "notebook",
    "revenue_analytics",
    "session_recording",
    "sharing_configuration",
    "survey",
    "ticket",
    "web_analytics",
    "activity_log",
    "error_tracking",
    "logs",
    "mcp_analytics",
    "metrics",
    "tracing",
    "replay_scanner",
    "toolbar",
    "llm_playground",
)

# Resources whose access comes from membership rather than resource-level AccessControl rows,
# so nothing sits above an object of this type to fall back to
RESOURCES_WITHOUT_RESOURCE_LEVEL_CONTROLS: frozenset[APIScopeObject] = frozenset({"organization", "project", "plugin"})

# Resource inheritance mapping - child resources inherit access from parent resources
RESOURCE_INHERITANCE_MAP: dict[APIScopeObject, APIScopeObject] = {
    "session_recording_playlist": "session_recording",
    "warehouse_table": "warehouse_objects",
    "warehouse_view": "warehouse_objects",
    "dataset": "llm_analytics",
    "llm_provider_key": "llm_analytics",
    "llm_prompt": "llm_analytics",
    "account": "customer_analytics",
    "customer_journey": "customer_analytics",
    "experiment_saved_metric": "experiment",
    "experiment_holdout": "experiment",
    "dashboard_template": "dashboard",
    # Marketing analytics doesn't have its own RBAC resource yet — inherit from
    # web_analytics so the existing per-team controls actually gate it (matches
    # the frontend mapping in sceneTypes.ts: Scene.MarketingAnalytics ->
    # AccessControlResourceType.WebAnalytics).
    "marketing_analytics": "web_analytics",
    # Vision actions are a second data model of the Replay Vision product (the
    # scanner's "and then…" automations) — configured via the same single
    # replay_scanner rule rather than a separate resource.
    "vision_action": "replay_scanner",
    # Vision alerts follow the same rule: configured via the scanner's access level.
    "vision_alert": "replay_scanner",
}

# Unlike RESOURCE_INHERITANCE_MAP above, where the child has no access of its own and just uses the
# parent's, this checks the child's own access first and falls back to the parent.
# For example:
# this table (object) -> this source (object) -> all tables (resource) -> all sources (resource) -> default
#
# The parent's id is read off the child's foreign key to it (DataWarehouseTable.external_data_source),
# so an entry only works when that foreign key exists. A null one means no parent, and the object
# skips it rather than inheriting: a self-managed table has no source, so no rule about sources
# may reach it.
RESOURCE_FALLBACK_MAP: dict[APIScopeObject, APIScopeObject] = {
    "warehouse_table": "external_data_source",
}

WAREHOUSE_ACCESS_SCOPES: frozenset[str] = frozenset(
    {
        "warehouse_objects",
        *(child for child, parent in RESOURCE_INHERITANCE_MAP.items() if parent == "warehouse_objects"),
    }
)

tracer = trace.get_tracer(__name__)


class UserAccessControlError(Exception):
    resource: APIScopeObject
    required_level: AccessControlLevel
    resource_id: Optional[str]

    def __init__(self, resource: APIScopeObject, required_level: AccessControlLevel, resource_id: Optional[str] = None):
        super().__init__(
            f"Access control failure. You don't have `{required_level}` access to the `{resource}` resource."
        )
        self.resource = resource
        self.required_level = required_level
        self.resource_id = resource_id


def get_field_access_control_map(model_class: type[Model]) -> dict[str, tuple[APIScopeObject, AccessControlLevel]]:
    """
    Dynamically retrieve field-level access control requirements from model fields.
    This function looks for fields decorated with @requires_access.
    """
    field_access_map = {}

    # Iterate through all fields in the model
    for field in model_class._meta.get_fields():
        # Check if the field has access control metadata
        if hasattr(field, "_access_control_resource") and hasattr(field, "_access_control_level"):
            field_access_map[field.name] = (field._access_control_resource, field._access_control_level)

    return field_access_map


def resource_to_display_name(resource: APIScopeObject) -> str:
    """Convert resource name to human-readable display name"""
    # Handle special cases
    if resource == "organization":
        return "organization"  # singular
    if resource == "hog_flow":
        return "workflows"
    if resource == "ai_observability_clusters":
        return "AI trace clusters"
    if resource == "external_data_source":
        return "data warehouse sources"
    if resource == "warehouse_objects":
        # Umbrella label for both warehouse tables and views (both children inherit from this)
        return "data warehouse tables & views"
    if resource == "llm_playground":
        # The playground is a single page, not a collection of objects
        return "LLM playground"

    # Default: replace underscores and add 's' for plural
    return f"{resource.replace('_', ' ')}s"


def ordered_access_levels(resource: APIScopeObject) -> list[AccessControlLevel]:
    if resource in ["project", "organization"]:
        return list(ACCESS_CONTROL_LEVELS_MEMBER)
    return list(ACCESS_CONTROL_LEVELS_RESOURCE)


def default_access_level(resource: APIScopeObject) -> AccessControlLevel:
    if resource in ["project"]:
        return "admin"
    if resource in ["organization"]:
        return "member"
    if resource in ["activity_log", "toolbar"]:
        return "viewer"
    return "editor"


def minimum_access_level(resource: APIScopeObject) -> AccessControlLevel:
    """Returns the minimum allowed access level for a resource. 'none' is not included if a minimum is specified."""
    if resource == "action":
        return "viewer"
    return "none"


def highest_access_level(resource: APIScopeObject) -> AccessControlLevel:
    """Returns the highest allowed access level for a resource."""
    if resource in ["activity_log", "toolbar"]:
        return "viewer"
    return ordered_access_levels(resource)[-1]


def access_level_satisfied_for_resource(
    resource: APIScopeObject, current_level: AccessControlLevel, required_level: AccessControlLevel
) -> bool:
    return ordered_access_levels(resource).index(current_level) >= ordered_access_levels(resource).index(required_level)


@frozen
class ResolvedAccess:
    """An access level plus which rule supplied it, so callers can attribute a resolution
    instead of re-deriving it. Enforcement reads only `access_level`.

    `source` names how the level was actually derived in the implementation — it must never be
    a nicer label for a different code path, and the implementation must never change to fit a label.

    `source` values:
    - "object": a rule on the object itself — a member/role row, or its default
    - "parent_object": a rule on its fallback parent — a table's source (RESOURCE_FALLBACK_MAP)
    - "resource": a resource-wide rule
    - "parent_resource": the fallback parent's resource-wide rule
    - "system_default": no rule anywhere — default_access_level() applies (also covers orgs
      without the entitlement, where rules are never consulted)
    - "org_admin": rules never consulted — the admin bypass
    - "creator": rules never consulted — the user created the object
    - "org_membership": the object is the organization itself — organizations have no access
      rules; the level comes from the user's OrganizationMembership.level (admin or member)
    """

    access_level: AccessControlLevel
    source: Literal[
        "object",
        "parent_object",
        "resource",
        "parent_resource",
        "system_default",
        "org_admin",
        "creator",
        "org_membership",
    ]
    # The source rule's subject: an everyone-row ("default"), a role row, or a member row.
    # None when no row decided.
    source_subject: Optional[Literal["member", "role", "default"]]
    # The resource the source rule belongs to — a table resolved through its source reports the
    # source's resource, and the system default reports the resource whose rules would apply
    # (the RESOURCE_INHERITANCE_MAP umbrella), not necessarily the object's own.
    source_resource: APIScopeObject
    # The source rule's resource_id — for a "parent_object" source this identifies which parent
    # (the source a table inherited from), so a display can name it. None when the rule is
    # resource-wide or no rule decided.
    source_resource_id: Optional[str] = None


def model_to_resource(model: Model) -> Optional[APIScopeObject]:
    """
    Given a model, return the resource type it represents
    """
    if hasattr(model, "_meta"):
        name = model._meta.model_name
    else:
        name = model.__class__.__name__.lower()

    # NOTE: These are special mappings where the 1-1 of APIScopeObject doesn't match
    if name == "team":
        return "project"
    if name == "featureflag":
        return "feature_flag"
    if name == "earlyaccessfeature":
        return "early_access_feature"
    if name == "plugin_config":
        return "plugin"
    if name == "sessionrecording":
        return "session_recording"
    if name == "sharingconfiguration":
        return "sharing_configuration"
    if name == "exportedasset":
        return "export"
    if name == "sessionrecordingplaylist":
        return "session_recording_playlist"
    if name == "savedheatmap":
        return "heatmap"
    if name == "experimentsavedmetric":
        return "experiment_saved_metric"
    if name == "experimentholdout":
        return "experiment_holdout"
    if name == "endpointversion":
        return "endpoint"
    # The workflow scope is "hog_flow" but the model is "hogflow"; its batch jobs and schedules have no
    # route of their own and inherit the parent workflow's access (same idea as endpointversion → endpoint).
    if name in ("hogflow", "hogflowbatchjob", "hogflowschedule"):
        return "hog_flow"
    if name == "externaldatasource":
        return "external_data_source"
    if name == "datawarehousesavedquery":
        return "warehouse_view"
    if name == "datawarehousesavedqueryfolder":
        return "warehouse_view"
    if name == "datawarehouseexpression":
        return "warehouse_view"
    if name == "datawarehousetable":
        return "warehouse_table"
    if name == "customerjourney":
        return "customer_journey"
    if name in ("replayscanner", "replayobservation"):
        return "replay_scanner"
    if name in ("visionaction", "visionactionrun"):
        return "vision_action"
    if name in ("visionalertconfiguration", "visionalertevent"):
        return "vision_alert"

    if name not in API_SCOPE_OBJECTS or name in INTERNAL_API_SCOPE_OBJECTS:
        return None

    return cast(APIScopeObject, name)


@cache
def _fallback_parent_fk(model: type[Model], parent_resource: APIScopeObject) -> Optional[ForeignKey]:
    """`model`'s foreign key to `parent_resource`, if it has one.

    Found by introspection rather than a declared field map so the relationship is read off the
    schema that already defines it. Cached because it depends only on the model class.
    """
    for field in model._meta.get_fields():
        # ForeignKey covers OneToOneField too, and excludes the reverse relations get_fields() also returns.
        if not isinstance(field, ForeignKey) or field.related_model is None:
            continue
        if model_to_resource(cast(Model, field.related_model)) == parent_resource:
            return field
    return None


def fallback_parent_object_id(obj: Model, parent_resource: APIScopeObject) -> Optional[str]:
    """Id of the object `obj` falls back to for access, or None when it has no such parent.

    None is what makes a self-managed table skip its source tiers rather than inherit from a
    source it doesn't have.
    """
    fk = _fallback_parent_fk(type(obj), parent_resource)
    if fk is None:
        return None
    parent_id = getattr(obj, fk.attname, None)
    return str(parent_id) if parent_id is not None else None


def fallback_parent_object(obj: Model, parent_resource: APIScopeObject) -> Optional[Model]:
    """The object `obj` falls back to for access, or None when it has no such parent.

    Read off the object's own relation — Django caches it on the instance — so callers that
    only need to display the parent never refetch it by id.
    """
    fk = _fallback_parent_fk(type(obj), parent_resource)
    if fk is None:
        return None
    return getattr(obj, fk.name, None)


@frozen
class ObjectAccessDecision:
    blocked_ids: frozenset[str]
    allowed_ids: frozenset[str]


class UserAccessControl:
    """
    UserAccessControl provides functions for checking unified access to all resources and objects from a Project level downwards.
    Typically a Team (Project) is required other than in certain circumstances, particularly when validating which projects a user has access to within an organization.
    """

    def __init__(self, user: User, team: Optional[Team] = None, organization_id: Optional[str] = None):
        self._user = user
        self._team = team
        self._cache: dict[str, list[AccessControl]] = {}
        self._sibling_team_access_controls: dict[int, UserAccessControl] = {}
        # Divergences this instance already reported. An instance lives for one request, and one
        # request resolves the same rules many times: project access several times, and each
        # object in a list response. The events carry no object id, so these repeats are
        # identical events. Report each distinct divergence once per request.
        self._reported_resolved_access_divergences: set[tuple] = set()

        if not organization_id and team:
            organization_id = str(team.organization_id)

        self._organization_id = organization_id

    def _clear_cache(self):
        self._cache = {}
        # Pop from __dict__ rather than hasattr/delattr
        # hasattr on an un-computed cached_property would re-populate the value we're clearing
        self.__dict__.pop("_cached_access_controls", None)
        self.__dict__.pop("blocked_resource_ids_by_scope", None)
        self.__dict__.pop("allowlisted_resource_ids_by_scope", None)
        self.__dict__.pop("blocked_resources", None)
        self.__dict__.pop("_organization_membership", None)
        self.__dict__.pop("_user_role_ids", None)
        # Dropped rather than cleared through: each sibling carries its own preloaded rows, and
        # some were primed from the caches being cleared here
        self._sibling_team_access_controls = {}

    def for_team_ids(self, team_ids: Iterable[int]) -> dict[int, "UserAccessControl"]:
        """This user's access control for each of the given teams, memoized on this instance.

        An instance only ever answers for the single team it was built with, and preloads that
        team's rows on first use. Resolving objects across several teams therefore needs one
        instance per team, and a request can reach that more than once (the file system tree
        spans every environment in a project and resolves access on both its filter and its
        serializer pass). Memoizing means the second pass reuses the first pass's instances,
        including their preloaded rows, instead of rebuilding and re-querying them.
        """
        by_team: dict[int, UserAccessControl] = {}
        missing: set[int] = set()
        for team_id in team_ids:
            if self._team is not None and team_id == self._team.id:
                by_team[team_id] = self
            elif team_id in self._sibling_team_access_controls:
                by_team[team_id] = self._sibling_team_access_controls[team_id]
            else:
                missing.add(team_id)

        if missing:
            for team in Team.objects.filter(id__in=missing):
                sibling = UserAccessControl(self._user, team=team)
                if sibling._organization_id == self._organization_id:
                    # Org membership and role ids don't vary by team, so seed them from this
                    # instance rather than letting each sibling re-query them. Written straight
                    # into __dict__ because that is where cached_property stores its value.
                    sibling.__dict__["_organization_membership"] = self._organization_membership
                    sibling.__dict__["_user_role_ids"] = self._user_role_ids
                self._sibling_team_access_controls[team.id] = sibling
                by_team[team.id] = sibling

        return by_team

    @cached_property
    def _organization_membership(self) -> Optional[OrganizationMembership]:
        # NOTE: This is optimized to reduce queries - we get the users membership _with_ the organization
        try:
            if not self._organization_id:
                return None
            return OrganizationMembership.objects.select_related("organization").get(
                organization_id=self._organization_id, user=self._user
            )
        except OrganizationMembership.DoesNotExist:
            return None

    @cached_property
    def _organization(self) -> Optional[Organization]:
        if self._organization_membership:
            return self._organization_membership.organization
        return None

    @cached_property
    def _user_role_ids(self):
        if not self.rbac_supported:
            # Early return to prevent an unnecessary lookup
            return []

        # Scoped to this organization: an AccessControl row can name a role belonging to a
        # different organization, and such a row must not grant or deny anything here.
        return list(
            cast(Any, self._user)
            .role_memberships.filter(role__organization_id=self._organization_id)
            .values_list("role_id", flat=True)
        )

    @cached_property
    def _cached_access_controls(self) -> list[_AccessControl]:
        """Single bulk fetch of every access control row this user is subject to for the team.

        Covers both resource-level (resource_id IS NULL) and object-level (resource_id set)
        rows, so all resolvers (object, resource, queryset) share one query instead of N narrow ones.

        Only team-scoped: org-scoped lookups (the `project` queryset, matched via
        `team__organization_id` across the org's teams) are not in this set, so
        `_get_access_controls` falls back to a targeted query for those.
        """
        if not EE_AVAILABLE or not self._team:
            return []
        # Annotate with team.organization_id only — avoids fetching the full ~150-column posthog_team row.
        return list(
            AccessControl.objects.annotate(_team_organization_id=F("team__organization_id")).filter(
                self._filter_options({"team_id": self._team.id})
            )
        )

    @property
    def user(self) -> User:
        """The principal this access control was built for. Callers that run HogQL on a user's behalf
        need it: warehouse/system table ACL is honored only when a real user reaches the database build
        (a userless build fails closed), so forwarding just the access control isn't enough."""
        return self._user

    @property
    def team(self) -> Optional[Team]:
        """The team this instance's checks are scoped to. Callers resolving access for objects
        that may live outside this team (e.g. a cross-environment listing) need it to tell
        whether they can reuse this instance or must build one scoped to the object's own team."""
        return self._team

    @property
    def rbac_supported(self) -> bool:
        if not self._organization:
            return False

        return self._organization.is_feature_available(AvailableFeature.ROLE_BASED_ACCESS)

    @property
    def access_controls_supported(self) -> bool:
        if not self._organization:
            return False

        return self._organization.is_feature_available(AvailableFeature.ACCESS_CONTROL)

    @property
    def is_organization_admin(self) -> bool:
        """Org owners/admins bypass object- and resource-level access control."""
        org_membership = self._organization_membership
        return bool(org_membership and org_membership.level >= OrganizationMembership.Level.ADMIN)

    def _is_creator(self, obj: Model) -> bool:
        """Whether the principal created the object, which grants them the highest access to it.
        Creator is a property of the principal, so a subclass that resolves for someone other than
        the requesting user must override this."""
        return getattr(obj, "created_by", None) == self._user

    # ------------------------------------------------------------
    # Access control helpers
    # ------------------------------------------------------------

    def _filter_options(self, filters: dict[str, Any]) -> Q:
        """
        Adds the 3 main filter options to the query
        """
        filters = self._db_filters(filters)
        return (
            Q(  # Access controls applying to this team
                **filters, organization_member=None, role=None
            )
            | Q(  # Access controls applying to this user
                # Scoped to this organization for the same reason as `_user_role_ids`: a row can name
                # a membership the user holds in a *different* organization, and such a row must not
                # grant or deny anything here.
                **filters,
                organization_member__user=self._user,
                organization_member__organization_id=self._organization_id,
                role=None,
            )
            | Q(  # Access controls applying to this user's roles
                **filters, organization_member=None, role__in=self._user_role_ids
            )
        )

    @staticmethod
    def _db_filters(filters: dict[str, Any]) -> dict[str, Any]:
        """Replace `team__organization_id` with `team_id__in` (the org's teams) for the DB query.
        The org id is a posthog_team column, so as a join predicate it forces a scan over every
        org's rows. A team_id predicate uses the index on ee_accesscontrol."""
        organization_id = filters.get("team__organization_id")
        if organization_id is None:
            return filters
        db_filters = {k: v for k, v in filters.items() if k != "team__organization_id"}
        db_filters["team_id__in"] = Team.objects.filter(organization_id=organization_id).values("id")
        return db_filters

    def _can_serve_from_preload(self, filters: dict) -> bool:
        """The preloaded set is `WHERE team_id = self._team.id` (+ the OR-3 precedence), so it
        can only answer team-scoped lookups. The org-scoped `project` queryset filter (via
        `team__organization_id`) must hit the DB directly."""
        return self._team is not None and filters.get("team_id") == self._team.id

    def _row_matches(self, ac: _AccessControl, filters: dict) -> bool:
        """In-memory equivalent of the targeted DB query's WHERE clause, applied to an already
        precedence-filtered pool. Mirrors the matching the targeted queryset would perform."""
        for filter_key, value in filters.items():
            if filter_key == "resource_id__isnull":
                if (ac.resource_id is None) != value:
                    return False
            elif filter_key == "team__organization_id":
                if ac._team_organization_id != value:  # type: ignore[attr-defined]
                    return False
            elif getattr(ac, filter_key) != value:
                return False
        return True

    def _get_access_controls(self, filters: dict) -> list[_AccessControl]:
        if not EE_AVAILABLE or not self.access_controls_supported:
            return []

        # Team-scoped lookups are served from the single bulk preload (filtered in memory);
        # org-scoped lookups fall through to a targeted query.
        if self._can_serve_from_preload(filters):
            return [ac for ac in self._cached_access_controls if self._row_matches(ac, filters)]

        key = json.dumps(filters, sort_keys=True)
        if key not in self._cache:
            with tracer.start_as_current_span("rbac.access_controls.db") as span:
                resource = filters.get("resource")
                if isinstance(resource, str):
                    span.set_attribute("rbac.resource", resource)
                span.set_attribute("rbac.has_resource_id", filters.get("resource_id") is not None)
                self._cache[key] = list(
                    AccessControl.objects.annotate(_team_organization_id=F("team__organization_id")).filter(
                        self._filter_options(filters)
                    )
                )
                span.set_attribute("rbac.row_count", len(self._cache[key]))

        return self._cache[key]

    def _access_controls_filters_for_object(self, resource: APIScopeObject, resource_id: str) -> dict:
        """
        Used when checking an individual object - gets all access controls for the object and its type
        """
        filters: dict[str, Any] = {"resource": resource, "resource_id": resource_id}
        # A create request has no team yet, so fall back to the organization scope like the queryset
        # variant does - otherwise serializing the create response raises AttributeError on team.id.
        if self._team:
            filters["team_id"] = self._team.id
        elif self._organization_id:
            filters["team__organization_id"] = str(self._organization_id)
        return filters

    def _access_controls_filters_for_resource(self, resource: APIScopeObject) -> dict:
        """
        Used when checking overall access to a resource
        """

        return {"team_id": self._team.id, "resource": resource, "resource_id": None}  # type: ignore

    def _access_controls_filters_for_queryset(self, resource: APIScopeObject) -> dict:
        """
        Used to filter out IDs from a queryset based on access controls where the specific resource is denied access
        """
        common_filters: dict[str, Any] = {"resource": resource, "resource_id__isnull": False}

        if self._team and resource != "project":
            common_filters["team_id"] = self._team.id
        elif self._organization_id:
            common_filters["team__organization_id"] = str(self._organization_id)

        return common_filters

    def _fill_filters_cache(self, filter_groups: list[dict], access_controls: list[_AccessControl]) -> None:
        for filters in filter_groups:
            key = json.dumps(filters, sort_keys=True)
            # TRICKY: We have to simulate the entire DB query here:
            self._cache[key] = [ac for ac in access_controls if self._row_matches(ac, filters)]

    # ------------------------------------------------------------
    # Preloading access controls
    # ------------------------------------------------------------

    def preload_object_access_controls(self, objects: list[Model]) -> None:
        """
        Preload access controls for a list of objects
        """
        if not EE_AVAILABLE:
            return

        filter_groups: list[dict] = []

        for obj in objects:
            resource = model_to_resource(obj)
            if not resource:
                return

            filter_groups.append(self._access_controls_filters_for_object(resource, str(obj.id)))  # type: ignore

        self._preload_filter_groups(filter_groups)

    def _preload_filter_groups(self, filter_groups: list[dict]) -> None:
        """Fill self._cache for these filter groups. When every group is team-scoped they're served
        from the single bulk preload (_cached_access_controls) in memory - no extra query; otherwise
        a targeted OR-combined query is issued for them."""
        if not filter_groups:
            return

        if all(self._can_serve_from_preload(filters) for filters in filter_groups):
            self._fill_filters_cache(filter_groups, self._cached_access_controls)
            return

        q = Q()
        for filters in filter_groups:
            q = q | self._filter_options(filters)
        self._fill_filters_cache(
            filter_groups,
            list(AccessControl.objects.annotate(_team_organization_id=F("team__organization_id")).filter(q)),
        )

    def preload_access_levels(self, team: Team, resource: APIScopeObject, resource_id: Optional[str] = None) -> None:
        """
        Checking permissions can involve multiple queries to AccessControl e.g. project level, global resource level, and object level
        As we can know this upfront, we can optimize this by loading all the controls we will need upfront.
        """
        if not EE_AVAILABLE:
            return

        # Question - are we fundamentally loading every access control for the given resource? If so should we accept that fact and just load them all?
        # doing all additional filtering in memory?

        filter_groups: list[dict] = []

        filter_groups.append(self._access_controls_filters_for_object(resource="project", resource_id=str(team.id)))
        filter_groups.append(self._access_controls_filters_for_resource(resource))

        if resource_id:
            filter_groups.append(self._access_controls_filters_for_object(resource, resource_id=resource_id))
        else:
            filter_groups.append(self._access_controls_filters_for_queryset(resource))

        self._preload_filter_groups(filter_groups)

    # ------------------------------------------------------------
    # Object level - checking conditions for specific items
    # ------------------------------------------------------------

    def access_level_for_object(
        self, obj: Model, resource: Optional[APIScopeObject] = None, explicit=False, specific_only=False
    ) -> Optional[AccessControlLevel]:
        """
        Access levels are strings - the order of which is determined at run time.
        We find all relevant access controls and then return the highest value

        Args:
            obj: The model object to check access for
            resource: The resource type (auto-detected if not provided)
            explicit: If True, only return explicit access controls (no fallback to default)
            specific_only: If True, only consider access controls with roles or organization members
        """

        resource = resource or model_to_resource(obj)
        org_membership = self._organization_membership

        if not resource or not org_membership:
            return None

        # Creators always have highest access
        if self._is_creator(obj):
            return highest_access_level(resource)

        # Org admins always have highest access
        if self.is_organization_admin:
            return highest_access_level(resource)

        if resource == "organization":
            # Organization access is controlled via membership level only
            if org_membership.level >= OrganizationMembership.Level.ADMIN:
                return "admin"
            return "member"

        # If access controls aren't supported, then we return the default access level
        if not self.access_controls_supported:
            return default_access_level(resource) if not explicit else None

        filters = self._access_controls_filters_for_object(resource, str(obj.id))  # type: ignore
        access_controls = self._get_access_controls(filters)

        # Filter to specific access controls if requested
        if specific_only:
            access_controls = [
                ac for ac in access_controls if ac.role_id is not None or ac.organization_member_id is not None
            ]
            # If we're looking for specific access controls and there are none we don't want to return the default access level
            if not access_controls:
                return None

        # If there is no specified controls on the resource then we return the default access level
        if not access_controls:
            return default_access_level(resource) if not explicit else None

        # If there are access controls we pick the highest level the user has
        return self._highest_access_from_rows(resource, access_controls).access_level

    def check_access_level_for_object(self, obj: Model, required_level: AccessControlLevel, explicit=False) -> bool:
        """
        Entry point for all permissions around a specific object.
        If any of the access controls have the same or higher level than the requested level, return True.

        Returns true or false if access controls are applied, otherwise None
        """

        resource = model_to_resource(obj)
        if not resource:
            # Permissions do not apply to models without a related scope
            return True

        access_level = self.get_user_access_level(obj, explicit=explicit)

        if not access_level:
            return False

        # If no access control exists
        return access_level_satisfied_for_resource(resource, access_level, required_level)

    def check_can_modify_access_levels_for_object(self, obj: Model) -> bool:
        """
        Special case for checking if the user can modify the access levels for an object.
        Unlike check_access_level_for_object, this requires that one of these conditions is true:
        1. The user is the creator of the object
        2. The user is explicitly a project admin
        3. The user is an org admin
        4. The user has "manager" access to the resource
        """

        if self._is_creator(obj):
            # TODO: Should this always be the case, even for projects?
            return True

        # If they aren't the creator then they need to be a project admin, org admin, or have "manager" access to the resource
        # TRICKY: If self._team isn't set, this is likely called for a Team itself so we pass in the object
        resource = model_to_resource(obj)
        project_admin_check = self.check_access_level_for_object(
            self._team or obj, required_level="admin", explicit=True
        )

        # Only check for "manager" access if it's not a project resource
        if resource != "project":
            return project_admin_check or self.check_access_level_for_object(
                obj, required_level="manager", explicit=True
            )

        return project_admin_check

    def get_access_source_for_object(
        self, obj: Model, resource: Optional[APIScopeObject] = None
    ) -> Optional[AccessSource]:
        """
        Determine how the user got access to an object.
        Returns None if the user has no access context.
        """
        resource = resource or model_to_resource(obj)
        org_membership = self._organization_membership

        if not resource or not org_membership:
            return None

        # Check if user is the creator
        if self._is_creator(obj):
            return AccessSource.CREATOR

        # Check if user is org admin
        if self.is_organization_admin:
            return AccessSource.ORGANIZATION_ADMIN

        # If access controls aren't supported, return default
        if not self.access_controls_supported:
            return AccessSource.DEFAULT

        # Get cached access controls for this object
        filters = self._access_controls_filters_for_object(resource, str(obj.id))  # type: ignore
        cached_controls = self._get_access_controls(filters)

        # Check for explicit member access
        if any(ac.organization_member_id == org_membership.id for ac in cached_controls):
            return AccessSource.EXPLICIT_MEMBER

        # Check for explicit role access
        if any(ac.role_id in self._user_role_ids for ac in cached_controls if ac.role_id):
            return AccessSource.EXPLICIT_ROLE

        # Check for project-level access
        if self._team is None:
            return AccessSource.DEFAULT

        project_filters = self._access_controls_filters_for_object("project", str(self._team.id))
        project_access_controls = self._get_access_controls(project_filters)
        if any(
            ac.resource_id == str(self._team.id) and ac.organization_member_id == org_membership.id
            for ac in project_access_controls
        ):
            return AccessSource.PROJECT_ADMIN

        # Default access
        return AccessSource.DEFAULT

    # ------------------------------------------------------------
    # Object level (specific) - checking conditions for specific items with a member or role
    # ------------------------------------------------------------

    def specific_access_level_for_object(self, obj: Model, explicit=False) -> Optional[AccessControlLevel]:
        """
        This is different than access_level_for_object, it's only looking at access levels that have
        a role or member for the object. It will fallback to access_level_for_object if none is found.
        """
        return self.access_level_for_object(obj, explicit=explicit, specific_only=True)

    # ------------------------------------------------------------
    # Resource level - checking conditions for the resource type
    # ------------------------------------------------------------

    def access_level_for_resource(self, resource: APIScopeObject) -> Optional[ResolvedAccess]:
        """
        Access levels are strings - the order of which is determined at run time.
        We find all relevant access controls and return the highest value, with the source rule
        attached so callers can attribute it.
        """

        # Check if this resource inherits access from a parent resource
        parent_resource = RESOURCE_INHERITANCE_MAP.get(resource)
        if parent_resource:
            # Use parent resource for access control checks
            return self.access_level_for_resource(parent_resource)

        if resource in RESOURCES_WITHOUT_RESOURCE_LEVEL_CONTROLS:
            return ResolvedAccess(
                access_level=default_access_level(resource),
                source="system_default",
                source_subject=None,
                source_resource=resource,
            )

        org_membership = self._organization_membership

        if not resource or not org_membership:
            # In any of these cases, we can't determine the access level
            return None

        # Org admins always have resource level access
        if self.is_organization_admin:
            return ResolvedAccess(
                access_level=highest_access_level(resource),
                source="org_admin",
                source_subject=None,
                source_resource=resource,
            )

        if not self.access_controls_supported:
            # If access controls aren't supported, then return the default access level
            return ResolvedAccess(
                access_level=default_access_level(resource),
                source="system_default",
                source_subject=None,
                source_resource=resource,
            )

        filters = self._access_controls_filters_for_resource(resource)
        access_controls = self._get_access_controls(filters)

        if not access_controls:
            return ResolvedAccess(
                access_level=default_access_level(resource),
                source="system_default",
                source_subject=None,
                source_resource=resource,
            )

        row = self._highest_access_from_rows(resource, access_controls)
        access = ResolvedAccess(
            access_level=row.access_level,
            source="resource",
            source_subject=self._row_subject(row),
            source_resource=resource,
        )
        self._report_resolved_access_divergence(
            "resource", resource, access, lambda: self.resolve_most_specific_resource_access(resource)
        )
        return access

    def has_access_levels_for_resource(self, resource: APIScopeObject) -> bool:
        if not self._team:
            # If there is no team, then there can't be any access controls on this resource
            return False

        # A resource that carries no resource-level controls has no such rules to find, whatever
        # rows exist. Answering True for one sends the object walk to `access_level_for_resource`,
        # which returns the built-in default for these resources — that would override the rules
        # written about the object itself, e.g. a project's own default.
        if resource in RESOURCES_WITHOUT_RESOURCE_LEVEL_CONTROLS:
            return False

        # Inheriting children (e.g. warehouse_view -> warehouse_objects) intentionally
        # bypass their own resource-level rows: only the parent (umbrella) is consulted.
        # This keeps the AC picker simple — admins configure one umbrella scope instead
        # of N child scopes — at the cost of ignoring any standalone resource-level row
        # written against a child. Object-level rows on the child are still honored via
        # specific_access_level_for_object, which queries the child resource directly.
        parent_resource = RESOURCE_INHERITANCE_MAP.get(resource)
        if parent_resource:
            return self.has_access_levels_for_resource(parent_resource)

        filters = self._access_controls_filters_for_resource(resource)
        access_controls = self._get_access_controls(filters)
        return bool(access_controls)

    def check_access_level_for_resource(self, resource: APIScopeObject, required_level: AccessControlLevel) -> bool:
        access = self.access_level_for_resource(resource)

        # For inherited resources, use the parent resource's access levels for comparison
        comparison_resource = RESOURCE_INHERITANCE_MAP.get(resource, resource)

        if not access:
            return False
        access_level = access.access_level

        return access_level_satisfied_for_resource(comparison_resource, access_level, required_level)

    def assert_access_level_for_resource(self, resource: APIScopeObject, required_level: AccessControlLevel) -> bool:
        """
        Stricter version of `check_access_level_for_resource`.
        Checks for specific object-level access as well as resource-level access.
        If they don't, raise a `UserAccessControlError`.
        """

        if not self.check_access_level_for_resource(resource, required_level):
            raise UserAccessControlError(resource, required_level)

        return True

    def has_any_specific_access_for_resource(
        self, resource: APIScopeObject, required_level: AccessControlLevel
    ) -> bool:
        """
        Check if the user has any object-level access controls for the given resource type
        that meet or exceed the required access level.

        This is useful when a user has "none" access at the resource level but may have
        specific grants to individual objects of that resource type.
        """
        org_membership = self._organization_membership

        if not resource or not org_membership:
            return False

        # Org admins always have access
        if self.is_organization_admin:
            return True

        # If access controls aren't supported, return False since we're looking for specific grants
        if not self.access_controls_supported:
            return False

        # Get all object-level access controls for this resource type
        filters = self._access_controls_filters_for_queryset(resource)
        access_controls = self._get_access_controls(filters)

        # These are already pre-loaded so filter what's in memory - read the FK id columns, not the
        # .role / .organization_member accessors, which would lazy-load one query per row.
        access_controls = [
            ac for ac in access_controls if ac.role_id is not None or ac.organization_member_id is not None
        ]

        # Check if any access control meets the required level
        for access_control in access_controls:
            if access_level_satisfied_for_resource(resource, access_control.access_level, required_level):
                return True

        return False

    def effective_access_level_for_resource(self, resource: APIScopeObject) -> Optional[AccessControlLevel]:
        """
        Get the effective access level for a resource, considering both resource-level
        and specific object-level access.

        This is used for UI navigation decisions - it allows users to see resource pages
        if they have specific object access, but does NOT grant creation permissions.

        Returns:
        - The resource-level access if it's not "none"
        - "viewer" if user has specific object access (allows page access but not creation)
        - None or "none" if user has no access at all
        """
        with tracer.start_as_current_span("rbac.effective_access_level_for_resource") as span:
            span.set_attribute("rbac.resource", str(resource))
            # First check resource-level access
            with tracer.start_as_current_span("rbac.resource_level_check"):
                access = self.access_level_for_resource(resource)
                resource_access = access.access_level if access else None

            # If resource access is not "none", return it directly
            if resource_access and resource_access != NO_ACCESS_LEVEL:
                span.set_attribute("rbac.path", "resource_level")
                return resource_access

            # If resource access is "none" or None, check for specific object access
            # For navigation purposes, if they have specific access to any objects,
            # grant them "viewer" level to see the resource page but NOT create new items
            with tracer.start_as_current_span("rbac.specific_access_fallback"):
                has_specific = self.has_any_specific_access_for_resource(resource, required_level="viewer")
            if has_specific:
                span.set_attribute("rbac.path", "specific_access")
                return "viewer"

            span.set_attribute("rbac.path", "no_access")
            return resource_access  # This will be "none" or None

    # ------------------------------------------------------------
    # Filtering querysets
    # ------------------------------------------------------------

    def filter_queryset_by_access_level(
        self, queryset: QuerySet, include_all_if_admin: bool = False, resource: Optional[APIScopeObject] = None
    ) -> QuerySet:
        # Filter queryset based on access controls, handling cases where user has "none" resource access
        # but may have specific object access

        model = cast(Model, queryset.model)
        # Callers that already know the resource must pass it: model_to_resource cannot map every
        # model name (LLMPrompt lowercases to "llmprompt"), and an unmapped model returns the
        # queryset unfiltered
        resource = resource or model_to_resource(model)

        if not resource:
            return queryset

        if include_all_if_admin and self.is_organization_admin:
            return queryset

        model_has_creator = hasattr(model, "created_by")

        filters = self._access_controls_filters_for_queryset(resource)
        access_controls = self._get_access_controls(filters)

        decision = self._blocked_and_allowed_object_ids(access_controls)

        # Apply filtering logic based on resource-level access
        if not self.has_resource_access(resource):
            # Resource-level "none": show only granted objects and the user's own objects, also
            # when there are no grants at all. Logic-layer and background callers reach this
            # filter with no permission layer above it, so it must fail closed on its own.
            if model_has_creator:
                queryset = queryset.filter(Q(id__in=decision.allowed_ids) | Q(created_by=self._user))
            else:
                queryset = queryset.filter(id__in=decision.allowed_ids)
        elif decision.blocked_ids:
            # Standard case: exclude explicitly blocked objects
            if model_has_creator:
                queryset = queryset.exclude(Q(id__in=decision.blocked_ids) & ~Q(created_by=self._user))
            else:
                queryset = queryset.exclude(id__in=decision.blocked_ids)

        return queryset

    def _blocked_and_allowed_object_ids(self, access_controls: list[_AccessControl]) -> ObjectAccessDecision:
        """Canonical object-level decision over a pool of object access controls (rows with
        `resource_id` set), returning an ObjectAccessDecision of blocked and allowed ids.

        Explicit-wins: if a resource_id has any explicit (role/member) rule, the object is
        allowed when any explicit rule grants non-"none", otherwise blocked. With no explicit
        rule, the object is blocked only when every default rule is "none".

        Reads the `role_id` / `organization_member_id` columns rather than the `.role` /
        `.organization_member` FK accessors — equivalent result (id is None iff the relation is
        None) without firing a query per row.
        """
        resource_id_access_levels: dict[str, list[str]] = {}
        for access_control in access_controls:
            resource_id_access_levels.setdefault(access_control.resource_id, []).append(access_control.access_level)

        blocked_resource_ids: set[str] = set()
        allowed_resource_ids: set[str] = set()

        for resource_id, access_levels in resource_id_access_levels.items():
            # Get the access controls for this specific resource_id to check role/member
            resource_access_controls = [ac for ac in access_controls if ac.resource_id == resource_id]

            # Only consider access controls that have explicit role or member (not defaults)
            explicit_access_controls = [
                ac for ac in resource_access_controls if ac.role_id is not None or ac.organization_member_id is not None
            ]

            if not explicit_access_controls:
                if all(access_level == NO_ACCESS_LEVEL for access_level in access_levels):
                    blocked_resource_ids.add(resource_id)
                # No explicit controls for this object - don't block it
                continue

            # Check if user has any non-"none" access to this specific object
            has_specific_access = any(ac.access_level != NO_ACCESS_LEVEL for ac in explicit_access_controls)

            if has_specific_access:
                allowed_resource_ids.add(resource_id)
            else:
                # All explicit access levels are "none" - block this object
                blocked_resource_ids.add(resource_id)

        return ObjectAccessDecision(
            blocked_ids=frozenset(blocked_resource_ids), allowed_ids=frozenset(allowed_resource_ids)
        )

    @cached_property
    def blocked_resource_ids_by_scope(self) -> dict[APIScopeObject, frozenset[str]]:
        """Per-resource set of object IDs the user is denied (effective access resolves to
        "none"), built from the single preload via the canonical object resolver.

        Consumed by HogQL object-level access control (schema filtering / printer guard) and by
        the query cache fingerprint. Empty for org admins (they bypass object AC) and when there is
        no team / EE / entitlement.
        """
        if not EE_AVAILABLE or not self._team or self.is_organization_admin:
            return {}

        if not self.access_controls_supported:
            # Without the entitlement, stale rules in the DB must be ignored, not enforced
            return {}

        object_rows_by_resource: dict[APIScopeObject, list[_AccessControl]] = defaultdict(list)
        for ac in self._cached_access_controls:
            if ac.resource_id is not None:
                object_rows_by_resource[cast(APIScopeObject, ac.resource)].append(ac)

        result: dict[APIScopeObject, frozenset[str]] = {}
        for resource, acs in object_rows_by_resource.items():
            blocked = self._blocked_and_allowed_object_ids(acs).blocked_ids
            if blocked:
                result[resource] = blocked
        return result

    @cached_property
    def allowlisted_resource_ids_by_scope(self) -> dict[APIScopeObject, frozenset[str]]:
        """Per-resource set of object IDs that are the *only* ones the user may read, for resources
        where they hold object-level grants but no resource-level access at all.

        This is the allowlist branch of `filter_queryset_by_access_level`: with "none" at the
        resource level, REST serves the route and narrows rows to the explicitly granted objects
        instead of merely removing denied ones. HogQL consumers must narrow the same way — a
        resource absent from this mapping falls back to removing `blocked_resource_ids_by_scope`.

        Empty for org admins and when there is no team / EE / entitlement, matching
        `blocked_resource_ids_by_scope`.
        """
        if not EE_AVAILABLE or not self._team or self.is_organization_admin:
            return {}

        if not self.access_controls_supported:
            # Without the entitlement, stale rules in the DB must be ignored, not enforced
            return {}

        object_rows_by_resource: dict[APIScopeObject, list[_AccessControl]] = defaultdict(list)
        for ac in self._cached_access_controls:
            if ac.resource_id is not None:
                object_rows_by_resource[cast(APIScopeObject, ac.resource)].append(ac)

        result: dict[APIScopeObject, frozenset[str]] = {}
        for resource, acs in object_rows_by_resource.items():
            allowed = self._blocked_and_allowed_object_ids(acs).allowed_ids
            if allowed and not self.has_resource_access(resource):
                result[resource] = allowed
        return result

    def has_resource_access(self, resource: APIScopeObject) -> bool:
        """Whether the user has any resource-level access (level is set and not "none")"""
        access = self.access_level_for_resource(resource)
        return bool(access and access.access_level != NO_ACCESS_LEVEL)

    @cached_property
    def has_project_access(self) -> bool:
        """Whether the user has any access to this instance's own team at the project level.

        Resource and object rules only answer what the user may do with a kind of thing inside a
        team, and fall back to `default_access_level` for a team that has no rules of its own. On
        their own they will therefore grant editor in a team the user was explicitly denied, so
        anything resolving access across several teams has to consult this separately.
        """
        if self._team is None:
            return True
        level = self.access_level_for_object(self._team, "project")
        return bool(level and level != NO_ACCESS_LEVEL)

    @cached_property
    def blocked_resources(self) -> list[str]:
        """Sorted list of resources the user has no access to at the resource level."""
        if self.is_organization_admin:
            return []
        candidate_resources = {ac.resource for ac in self._cached_access_controls if ac.resource_id is None}
        return sorted(resource for resource in candidate_resources if not self.has_resource_access(resource))

    def object_ids_matching(
        self, resources: Sequence[APIScopeObject], predicate: Callable[[_AccessControl], bool]
    ) -> dict[str, set[str]]:
        """Object ids whose access control rows satisfy `predicate`, per resource.

        Considers the same rows the queryset filters consider: every row applicable to this user
        for the resource, whether it came from the team default, their membership, or a role.
        Rows without a `resource_id` are resource-level rather than object-level and are skipped.

        `predicate` decides per row, so a resource appears in the result when *any* of its rows
        matches. Callers wanting a rule that depends on the whole set for an object (for example
        "explicit rules win over defaults") want `_blocked_and_allowed_object_ids` instead.
        """
        matched: dict[str, set[str]] = {}
        for resource in resources:
            object_ids = {
                access_control.resource_id
                for access_control in self._get_access_controls(self._access_controls_filters_for_queryset(resource))
                if access_control.resource_id and predicate(access_control)
            }
            if object_ids:
                matched[resource] = object_ids
        return matched

    def none_denied_object_ids(self, resources: Sequence[APIScopeObject]) -> dict[str, set[str]]:
        """Object ids the user has a 'none' grant on, per resource.

        Mirrors the row matching `filter_and_annotate_file_system_queryset` does in SQL: any
        applicable row (team default, member, or role) at level 'none' denies the object. Kept as
        a named method rather than a predicate at the call site so the tree filter's two halves,
        this one and its SQL counterpart, can't drift onto different rules.
        """
        return self.object_ids_matching(resources, lambda ac: ac.access_level == NO_ACCESS_LEVEL)

    def filter_and_annotate_file_system_queryset(
        self, queryset: QuerySet["FileSystem"], extra_denied_refs: Optional[dict[tuple[str, int], list[str]]] = None
    ) -> QuerySet["FileSystem"]:
        """
        Annotate each FileSystem with the effective_access_level (either 'none' or 'some')
        and exclude items that end up with 'none', unless the user is the creator or project-admin or org-admin/staff.

        `extra_denied_refs` maps a (file system type, team_id) pair to refs denied by a grant this
        queryset's own `ref`-to-`resource_id` comparison can't see, because the ref isn't the
        object's primary key. Keyed by team_id, like the rest of this method, because the queryset
        can span every environment in a project - a denial made in one team must not hide a
        same-valued ref that happens to belong to a different team.
        """
        user = self._user

        # 1) If the user is staff or org-admin, they can see everything
        if user.is_staff or self.is_organization_admin:
            return queryset

        if not EE_AVAILABLE:
            return queryset

        if not self.access_controls_supported:
            # Without the entitlement, stale rules in the DB must be ignored, not enforced
            return queryset

        # Subquery to check if user has "admin" on the FileSystem's team/project
        is_admin_for_project_subquery = (
            AccessControl.objects.filter(
                team_id=OuterRef("team_id"),
                resource="project",
                resource_id=Cast(OuterRef("team_id"), CharField()),
            )
            .filter(
                Q(organization_member__user=user)
                | Q(role__in=self._user_role_ids)
                | Q(organization_member=None, role=None)
            )
            .filter(access_level="admin")
            .values("pk")[:1]
        )

        # Subquery to check whether the user has "none" for this specific FileSystem
        is_none_subquery = (
            AccessControl.objects.filter(
                team_id=OuterRef("team_id"),
                resource=OuterRef("type"),
                resource_id=OuterRef("ref"),
            )
            .filter(
                Q(organization_member__user=user)
                | Q(role__in=self._user_role_ids)
                | Q(organization_member=None, role=None)
            )
            .filter(access_level="none")
            .values("pk")[:1]
        )

        # 2) Annotate the project-admin check + the is_none check
        queryset = queryset.annotate(
            is_project_admin=Exists(is_admin_for_project_subquery),
            is_none_access=Exists(is_none_subquery),
        )

        # 3) Compute effective_access_level:
        #
        #    - If is_none_access is True => "none"
        #    - Else => "some" ("editor" or "viewer")
        queryset = queryset.annotate(
            effective_access_level=Case(
                When(is_none_access=True, then=Value("none")),
                default=Value("some"),
                output_field=CharField(),
            )
        )

        # 4) Exclude items that are "none" if the user is not the creator,
        #    not a project admin, and not an org-admin/staff (already handled in step #1).
        denied = Q(effective_access_level="none")
        for (entry_type, team_id), refs in (extra_denied_refs or {}).items():
            if refs:
                denied |= Q(team_id=team_id, type=entry_type, ref__in=refs)

        queryset = queryset.exclude(denied & Q(is_project_admin=False) & ~Q(created_by=user))

        return queryset

    # ------------------------------------------------------------
    # User access level
    # ------------------------------------------------------------

    def _object_access_level_precheck(
        self, resource: APIScopeObject, is_creator: bool, explicit: bool = False
    ) -> tuple[bool, Optional[ResolvedAccess]]:
        """Guard steps of object access resolution that don't need the object's own AC rows.

        Returns (resolved, resolution): when `resolved` is True, `resolution` is the final answer
        and the object's rows must not be consulted. Shared by `get_user_access_level` and
        `bulk_object_access_levels` so the single and bulk paths cannot drift.
        """
        org_membership = self._organization_membership
        if not org_membership:
            return True, None

        # Creators and org admins always have highest access
        if is_creator:
            return True, ResolvedAccess(
                access_level=highest_access_level(resource),
                source="creator",
                source_subject=None,
                source_resource=resource,
            )
        if self.is_organization_admin:
            return True, ResolvedAccess(
                access_level=highest_access_level(resource),
                source="org_admin",
                source_subject=None,
                source_resource=resource,
            )

        if resource == "organization":
            # Organization access is controlled via membership level only
            membership_level: AccessControlLevel = (
                "admin" if org_membership.level >= OrganizationMembership.Level.ADMIN else "member"
            )
            return True, ResolvedAccess(
                access_level=membership_level,
                source="org_membership",
                source_subject=None,
                source_resource=resource,
            )

        if not self.access_controls_supported:
            if explicit:
                return True, None
            return True, ResolvedAccess(
                access_level=default_access_level(resource),
                source="system_default",
                source_subject=None,
                source_resource=resource,
            )

        return False, None

    @staticmethod
    def _highest_access_from_rows(resource: APIScopeObject, access_controls: list[_AccessControl]) -> _AccessControl:
        """Pick the row that supplies the highest access level.

        Several rows can tie at the highest level. The level is the same whichever we pick, but the
        caller reports which row decided (source_subject, source_resource_id), so the pick must be
        deterministic: the user's own member row wins over a role row, which wins over the everyone-row.
        """
        levels = ordered_access_levels(resource)
        specificity = {"default": 0, "role": 1, "member": 2}
        return max(
            access_controls,
            key=lambda ac: (levels.index(ac.access_level), specificity[UserAccessControl._row_subject(ac)]),
        )

    @staticmethod
    def _row_subject(access_control: _AccessControl) -> Literal["member", "role", "default"]:
        if access_control.organization_member_id is not None:
            return "member"
        if access_control.role_id is not None:
            return "role"
        return "default"

    def _object_access_level_from_rows(
        self,
        resource: APIScopeObject,
        object_access_controls: list[_AccessControl],
        explicit: bool = False,
        fallback_parent_id: Optional[str] = None,
    ) -> Optional[ResolvedAccess]:
        """Row-based object access resolution, most specific rule first: explicit (role/member) object
        rows, then the fallback parent's object rows, then resource-level rows, then the parent's
        resource-level rows, then default object rows, then the resource default. Shared by
        `get_user_access_level` and `bulk_object_access_levels`, which read only `.access_level`.
        """
        parent = RESOURCE_FALLBACK_MAP.get(resource) if fallback_parent_id else None

        explicit_rows = [
            ac for ac in object_access_controls if ac.role_id is not None or ac.organization_member_id is not None
        ]
        if explicit_rows:
            row = self._highest_access_from_rows(resource, explicit_rows)
            return ResolvedAccess(
                access_level=row.access_level,
                source="object",
                source_subject=self._row_subject(row),
                source_resource=resource,
                source_resource_id=row.resource_id,
            )

        if parent:
            parent_rows = self._get_access_controls(
                self._access_controls_filters_for_object(parent, cast(str, fallback_parent_id))
            )
            if parent_rows:
                row = self._highest_access_from_rows(parent, parent_rows)
                return ResolvedAccess(
                    access_level=row.access_level,
                    source="parent_object",
                    source_subject=self._row_subject(row),
                    source_resource=parent,
                    source_resource_id=row.resource_id,
                )

        if self.has_access_levels_for_resource(resource):
            access_for_resource = self.access_level_for_resource(resource)
            if access_for_resource:
                return access_for_resource

        if parent and self.has_access_levels_for_resource(parent):
            access_for_parent = self.access_level_for_resource(parent)
            if access_for_parent:
                return replace(access_for_parent, source="parent_resource")

        if object_access_controls:
            row = self._highest_access_from_rows(resource, object_access_controls)
            return ResolvedAccess(
                access_level=row.access_level,
                source="object",
                source_subject=self._row_subject(row),
                source_resource=resource,
                source_resource_id=row.resource_id,
            )

        if explicit:
            return None
        return ResolvedAccess(
            access_level=default_access_level(resource),
            source="system_default",
            source_subject=None,
            source_resource=RESOURCE_INHERITANCE_MAP.get(resource, resource),
        )

    @staticmethod
    def _fallback_parent_id(obj: Model, resource: APIScopeObject) -> Optional[str]:
        parent = RESOURCE_FALLBACK_MAP.get(resource)
        return fallback_parent_object_id(obj, parent) if parent else None

    def get_user_access_level(self, obj: Model, explicit=False) -> Optional[AccessControlLevel]:
        resource = model_to_resource(obj)
        if not resource:
            return None

        resolved, access = self._object_access_level_precheck(resource, self._is_creator(obj), explicit=explicit)
        if resolved:
            return access.access_level if access else None

        object_access_controls = self._get_access_controls(
            self._access_controls_filters_for_object(resource, str(obj.id))  # type: ignore
        )
        access = self._object_access_level_from_rows(
            resource,
            object_access_controls,
            explicit=explicit,
            fallback_parent_id=self._fallback_parent_id(obj, resource),
        )
        if not explicit:
            # explicit=True changes the enforced answer but not the future one, so comparing
            # there would report divergence that is really just the flag
            self._report_resolved_access_divergence(
                "object", resource, access, lambda: self.resolve_most_specific_object_access(obj)
            )
        return access.access_level if access else None

    def bulk_object_access_levels(
        self,
        resource: APIScopeObject,
        objects: Sequence[tuple[str, Optional[int]]],
    ) -> dict[str, Optional[AccessControlLevel]]:
        """Resolve the user's access level for many objects of one resource type at once.

        `objects` is a sequence of (object_pk_str, created_by_id) pairs. Semantics match
        `get_user_access_level`, but object rows come from the bulk preload grouped in memory,
        so no per-object queries are issued.
        """
        # Warehouse tables aren't listed by either caller (search, the file tree). If that changes, load
        # the parent ids here too, so access is checked against the source and not just the table.
        parent = RESOURCE_FALLBACK_MAP.get(resource)
        if parent:
            raise NotImplementedError(f"bulk_object_access_levels cannot resolve `{resource}` through `{parent}`")

        if not objects:
            return {}

        results: dict[str, Optional[AccessControlLevel]] = {}
        rows_by_object_id: Optional[dict[str, list[_AccessControl]]] = None

        for object_id, created_by_id in objects:
            is_creator = created_by_id is not None and created_by_id == self._user.id
            resolved, access = self._object_access_level_precheck(resource, is_creator)
            if resolved:
                results[object_id] = access.access_level if access else None
                continue

            if rows_by_object_id is None:
                rows_by_object_id = defaultdict(list)
                for ac in self._get_access_controls(self._access_controls_filters_for_queryset(resource)):
                    rows_by_object_id[ac.resource_id].append(ac)

            access = self._object_access_level_from_rows(resource, rows_by_object_id.get(object_id, []))
            results[object_id] = access.access_level if access else None

        return results

    # ------------------------------------------------------------
    # Most-specific-wins resolution (RFC 557). Not enforced.
    #
    # These methods resolve access by specificity:
    # - Most specific subject first: member override -> max(role overrides) -> the object's
    #   own default.
    # - When the resource is in RESOURCE_FALLBACK_MAP (e.g. `warehouse_table` ->
    #   `external_data_source`), access resolves as: rules on the object -> its parent ->
    #   the resource -> the parent's resource.
    # The first rule found in this order decides, even when it gives a lower level.
    # The enforced methods resolve differently: they take the highest level across the
    # member and role overrides, and rules on the resource win over the object's own default.
    #
    # DO NOT CALL THESE METHODS FOR ENFORCEMENT YET.
    # Call `get_user_access_level`, `check_access_level_for_object`, or
    # `access_level_for_resource` instead.
    # ------------------------------------------------------------

    def _rows_by_subject(self, rows: list[_AccessControl]) -> list[list[_AccessControl]]:
        """Group one scope's rows by subject, most specific first: the member's own rows, then
        the rows of their roles, then the rows that apply to everyone. Empty groups are removed."""
        by_subject: dict[str, list[_AccessControl]] = {"member": [], "role": [], "default": []}
        for ac in rows:
            by_subject[self._row_subject(ac)].append(ac)
        return [group for group in by_subject.values() if group]

    def resolve_most_specific_object_access(self, obj: Model) -> Optional[ResolvedAccess]:
        """Future source of truth for object access — NOT enforced yet, see the section comment.

        This method has no `explicit` parameter. It always returns the full answer. For the
        `explicit=True` behavior of the enforced methods, check
        `resolved.source != "system_default"`.
        """
        resource = model_to_resource(obj)
        if not resource:
            return None

        resolved, access = self._object_access_level_precheck(resource, self._is_creator(obj))
        if resolved:
            return access

        fallback_parent_id = self._fallback_parent_id(obj, resource)
        parent = RESOURCE_FALLBACK_MAP.get(resource) if fallback_parent_id else None

        object_rows = self._get_access_controls(self._access_controls_filters_for_object(resource, str(obj.id)))  # type: ignore
        for subject_rows in self._rows_by_subject(object_rows):
            row = self._highest_access_from_rows(resource, subject_rows)
            return ResolvedAccess(
                access_level=row.access_level,
                source="object",
                source_subject=self._row_subject(row),
                source_resource=resource,
                source_resource_id=row.resource_id,
            )

        if parent:
            parent_rows = self._get_access_controls(
                self._access_controls_filters_for_object(parent, cast(str, fallback_parent_id))
            )
            for subject_rows in self._rows_by_subject(parent_rows):
                row = self._highest_access_from_rows(parent, subject_rows)
                return ResolvedAccess(
                    access_level=row.access_level,
                    source="parent_object",
                    source_subject=self._row_subject(row),
                    source_resource=parent,
                    source_resource_id=row.resource_id,
                )

        if self.has_access_levels_for_resource(resource):
            access_for_resource = self.resolve_most_specific_resource_access(resource)
            if access_for_resource:
                return access_for_resource

        if parent and self.has_access_levels_for_resource(parent):
            access_for_parent = self.resolve_most_specific_resource_access(parent)
            if access_for_parent:
                return replace(access_for_parent, source="parent_resource")

        return ResolvedAccess(
            access_level=default_access_level(resource),
            source="system_default",
            source_subject=None,
            source_resource=RESOURCE_INHERITANCE_MAP.get(resource, resource),
        )

    def resolve_most_specific_resource_access(self, resource: APIScopeObject) -> Optional[ResolvedAccess]:
        """Future source of truth for resource access — NOT enforced yet, see the section comment.

        The guards are the same as in `access_level_for_resource`. Only the row step differs:
        the most specific subject that has a row decides.
        """
        parent_resource = RESOURCE_INHERITANCE_MAP.get(resource)
        if parent_resource:
            return self.resolve_most_specific_resource_access(parent_resource)

        if resource in RESOURCES_WITHOUT_RESOURCE_LEVEL_CONTROLS:
            return ResolvedAccess(
                access_level=default_access_level(resource),
                source="system_default",
                source_subject=None,
                source_resource=resource,
            )

        if not resource or not self._organization_membership:
            return None

        if self.is_organization_admin:
            return ResolvedAccess(
                access_level=highest_access_level(resource),
                source="org_admin",
                source_subject=None,
                source_resource=resource,
            )

        if not self.access_controls_supported:
            return ResolvedAccess(
                access_level=default_access_level(resource),
                source="system_default",
                source_subject=None,
                source_resource=resource,
            )

        rows = self._get_access_controls(self._access_controls_filters_for_resource(resource))
        for subject_rows in self._rows_by_subject(rows):
            row = self._highest_access_from_rows(resource, subject_rows)
            return ResolvedAccess(
                access_level=row.access_level,
                source="resource",
                source_subject=self._row_subject(row),
                source_resource=resource,
            )

        return ResolvedAccess(
            access_level=default_access_level(resource),
            source="system_default",
            source_subject=None,
            source_resource=resource,
        )

    def _report_resolved_access_divergence(
        self,
        kind: Literal["object", "resource"],
        resource: APIScopeObject,
        current: Optional[ResolvedAccess],
        proposed_fn: Callable[[], Optional[ResolvedAccess]],
    ) -> None:
        """Capture a PostHog event when the enforced resolution and the most-specific one disagree.

        This is read-only telemetry for the resolution migration. It does not change the enforced
        answer. `proposed_fn` runs only after the guards pass, so a skipped call does not pay
        for the second resolution. Subclasses are skipped: SubjectAccessControl resolves
        another subject's access for display, and those divergences do not describe this user.
        """
        if type(self) is not UserAccessControl or current is None:
            return
        try:
            proposed = proposed_fn()
            if proposed is None or current.access_level == proposed.access_level:
                return

            key = (kind, resource, current.access_level, proposed.access_level, current.source, proposed.source)
            if key in self._reported_resolved_access_divergences:
                return
            self._reported_resolved_access_divergences.add(key)

            order = ordered_access_levels(resource)
            direction = (
                "widens" if order.index(proposed.access_level) > order.index(current.access_level) else "narrows"
            )
            # The event carries no object ids and no emails. Aggregate counts are enough for the migration.
            posthoganalytics.capture(
                distinct_id=self._user.distinct_id,
                event="most specific access control decision diverged",
                properties={
                    "kind": kind,
                    "resource": resource,
                    "direction": direction,
                    "current_level": current.access_level,
                    "current_source": current.source,
                    "current_source_subject": current.source_subject,
                    "proposed_level": proposed.access_level,
                    "proposed_source": proposed.source,
                    "proposed_source_subject": proposed.source_subject,
                    "team_id": self._team.id if self._team else None,
                    "organization_id": str(self._organization_id) if self._organization_id else None,
                },
            )
        except Exception as e:
            # Shadow code must never break the enforced answer. Failures surface in error
            # tracking instead of disappearing, so a broken shadow resolver gets noticed.
            capture_exception(e)


def visible_teams_for_user(
    organization: Organization,
    user_access_control: Optional["UserAccessControl"],
    user_permissions: "UserPermissions",
) -> QuerySet[Team]:
    """Teams in `organization` the user can see.

    Both access control systems apply, and filtering on only one of them leaks projects the
    other hides. Callers that need visible teams should use this rather than reimplementing it.
    """
    teams = (
        user_access_control.filter_queryset_by_access_level(organization.teams.all(), include_all_if_admin=True)
        if user_access_control
        else organization.teams.none()
    )
    return teams.filter(id__in=user_permissions.team_ids_visible_for_user)
