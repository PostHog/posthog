"""Preview of the RFC 557 resolution change, per rule subject.

For one team, compare the enforced resolution with the most-specific resolution for every rule
subject (the everyone-default, each named role, each named member) against every object that has
rules and every resource that has resource-level rows. Return one change record per (subject,
scope) pair whose level differs. Members are never enumerated: members with the same applicable
rules resolve identically, so one subject-level record covers all of them.

Read-only. Nothing here changes enforcement. The settings preview page and the divergent-org
sweep command are the only callers.
"""

from typing import Literal, Optional, cast

from django.db.models import Model

from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.scopes import APIScopeObject

from products.access_control.backend.facade.subject_access_control import SubjectAccessControl
from products.access_control.backend.facade.user_access_control import (
    RESOURCES_WITHOUT_RESOURCE_LEVEL_CONTROLS,
    ResolvedAccess,
    UserAccessControl,
    ordered_access_levels,
)
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role, RoleMembership

SubjectType = Literal["everyone", "role", "member"]

# Rows on these resources resolve the same under both ladders, or have no object model to load
_SKIPPED_RESOURCES = frozenset({"organization", "plugin"})


@frozen
class SubjectRef:
    """The rule subject a change applies to. A change applies to the members the subject reaches
    who have no more specific rule of their own."""

    type: SubjectType
    id: Optional[str]
    name: str


@frozen
class ResolvedLevel:
    level: str
    source: str
    source_subject: Optional[str]
    # Name of the member or role whose row decided, so the explanation can say which role's
    # grant applies today. None when the everyone-row or a built-in default decided.
    subject_name: Optional[str] = None


@frozen
class ResolutionChange:
    subject: SubjectRef
    scope: Literal["object", "resource"]
    resource: str
    object_id: Optional[str]
    object_name: Optional[str]
    current: ResolvedLevel
    proposed: ResolvedLevel
    direction: Literal["gains", "loses"]


@frozen
class _Subject:
    ref: SubjectRef
    access: SubjectAccessControl
    member_user_id: Optional[int]


def _resolved_level(access: ResolvedAccess, subject_name: Optional[str] = None) -> ResolvedLevel:
    return ResolvedLevel(
        level=access.access_level,
        source=access.source,
        source_subject=access.source_subject,
        subject_name=subject_name,
    )


def _deciding_subject_name(
    subject: SubjectAccessControl,
    access: ResolvedAccess,
    role_names: dict[str, str],
    member_names: dict[str, str],
) -> Optional[str]:
    """Name of the member or role whose row decided `access`.

    The walks report which kind of subject decided (`source_subject`) but not which row. The
    deciding row is re-picked from the same cached pool: the highest row of that kind in the
    scope the walk reported.
    """
    if access.source_subject not in ("role", "member"):
        return None
    if access.source in ("object", "parent_object"):
        if access.source_resource_id is None:
            return None
        filters = subject._access_controls_filters_for_object(access.source_resource, access.source_resource_id)
    elif access.source in ("resource", "parent_resource"):
        filters = subject._access_controls_filters_for_resource(access.source_resource)
    else:
        return None
    rows = [row for row in subject._get_access_controls(filters) if subject._row_subject(row) == access.source_subject]
    if not rows:
        return None
    row = subject._highest_access_from_rows(access.source_resource, rows)
    if row.role_id is not None:
        return role_names.get(str(row.role_id))
    if row.organization_member_id is not None:
        return member_names.get(str(row.organization_member_id))
    return None


def _enforced_object_access(subject: SubjectAccessControl, obj: Model, resource: APIScopeObject) -> ResolvedAccess:
    """The enforced resolution of `obj` for `subject`, with provenance.

    Mirrors `get_user_access_level`, which returns the level only. The preview needs the source
    to explain each change, so it walks the same private methods. The caller already excluded
    the precheck outcomes (creators, org admins, missing entitlement), so the row walk is the
    whole answer.
    """
    rows = subject._get_access_controls(subject._access_controls_filters_for_object(resource, str(obj.pk)))
    access = subject._object_access_level_from_rows(
        resource, rows, fallback_parent_id=subject._fallback_parent_id(obj, resource)
    )
    assert access is not None  # explicit=False never returns None here
    return access


def _subject_key(row: AccessControl) -> tuple:
    if row.organization_member_id is not None:
        return ("member", str(row.organization_member_id))
    if row.role_id is not None:
        return ("role", str(row.role_id))
    return ("everyone",)


def _build_subjects(
    team: Team, user_access_control: UserAccessControl, rows: list[AccessControl]
) -> tuple[list[_Subject], dict[str, str], dict[str, str]]:
    """One subject per distinct rule target in `rows`, plus the everyone-default, and the
    role and member display names keyed by id.

    Org-admin members are excluded: both resolutions give them the highest level. Role ids of
    each member subject are prefetched here, so subjects do not query per member.
    """
    acting_membership = user_access_control._organization_membership
    if acting_membership is None:
        return [], {}, {}

    member_ids = {row.organization_member_id for row in rows if row.organization_member_id is not None}
    role_ids = {row.role_id for row in rows if row.role_id is not None}

    memberships = list(
        OrganizationMembership.objects.filter(id__in=member_ids, organization_id=team.organization_id).select_related(
            "user"
        )
    )
    roles = Role.objects.filter(id__in=role_ids, organization_id=team.organization_id)
    # Role membership is keyed by user, matching SubjectAccessControl._user_role_ids
    role_ids_by_user: dict[int, list[str]] = {}
    for rm in RoleMembership.objects.filter(
        role__organization_id=team.organization_id, user_id__in=[membership.user_id for membership in memberships]
    ):
        role_ids_by_user.setdefault(rm.user_id, []).append(str(rm.role_id))

    subjects: list[_Subject] = [
        _Subject(
            ref=SubjectRef(type="everyone", id=None, name="Everyone"),
            access=SubjectAccessControl(user_access_control.user, team, org_membership=acting_membership),
            member_user_id=None,
        )
    ]
    for role in roles:
        subjects.append(
            _Subject(
                ref=SubjectRef(type="role", id=str(role.id), name=role.name),
                access=SubjectAccessControl(
                    user_access_control.user, team, org_membership=acting_membership, role_id=str(role.id)
                ),
                member_user_id=None,
            )
        )
    for membership in memberships:
        if membership.level >= OrganizationMembership.Level.ADMIN:
            continue
        user = membership.user
        name = f"{user.first_name} {user.last_name}".strip() or user.email
        subject = SubjectAccessControl(
            user_access_control.user, team, org_membership=acting_membership, member=membership
        )
        subjects.append(
            _Subject(
                ref=SubjectRef(type="member", id=str(membership.id), name=name),
                access=subject,
                member_user_id=membership.user_id,
            )
        )

    for subject in subjects:
        subject_role_ids = (
            role_ids_by_user.get(subject.member_user_id, []) if subject.member_user_id is not None else None
        )
        subject.access.preload_access_controls(rows, subject_role_ids=subject_role_ids)

    role_names = {str(role.id): role.name for role in roles}
    member_names = {subject.ref.id or "": subject.ref.name for subject in subjects if subject.ref.type == "member"}
    return subjects, role_names, member_names


def _load_objects(team: Team, resource: str, object_ids: list[str]) -> dict[str, tuple[Model, Optional[str]]]:
    """Map {object_id -> (instance, display name)} for one resource. Empty when the resource has
    no display model, which also means resolution has no model class to work with."""
    if resource == "project":
        # Project rules point at the team itself
        return {str(team.pk): (team, team.name)} if str(team.pk) in object_ids else {}

    # Deferred to break the import cycle: the settings presentation module imports this module
    # for its endpoint.
    from products.access_control.backend.presentation.access_control_settings import (  # noqa: PLC0415
        _display_model,
        _resolve_object_names,
    )

    display = _display_model(resource)
    if display is None:
        return {}
    names = _resolve_object_names(resource, object_ids, team.pk)
    try:
        instances = display.model._base_manager.filter(team_id=team.pk, pk__in=object_ids)
    except Exception as e:
        capture_exception(e, {"resource": resource})
        return {}
    result: dict[str, tuple[Model, Optional[str]]] = {}
    for obj in instances:
        object_id = str(obj.pk)
        name = names.get(object_id)
        result[object_id] = (obj, name.name if name else None)
    return result


def _relevant_subject_keys(rows: list[AccessControl]) -> set[tuple]:
    return {_subject_key(row) for row in rows}


def build_resolution_preview(team: Team, user_access_control: UserAccessControl) -> list[ResolutionChange]:
    """Every (subject, scope) pair on `team` whose enforced and most-specific resolutions differ."""
    if not team.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
        return []

    rows = [row for row in AccessControl.objects.filter(team=team) if row.resource not in _SKIPPED_RESOURCES]
    if not rows:
        return []

    subjects, role_names, member_names = _build_subjects(team, user_access_control, rows)
    changes: list[ResolutionChange] = []

    def compare(
        subject: _Subject,
        scope: Literal["object", "resource"],
        resource: str,
        current: Optional[ResolvedAccess],
        proposed: Optional[ResolvedAccess],
        object_id: Optional[str] = None,
        object_name: Optional[str] = None,
    ) -> None:
        if current is None or proposed is None or current.access_level == proposed.access_level:
            return
        order = ordered_access_levels(cast(APIScopeObject, resource))
        direction: Literal["gains", "loses"] = (
            "gains" if order.index(proposed.access_level) > order.index(current.access_level) else "loses"
        )
        changes.append(
            ResolutionChange(
                subject=subject.ref,
                scope=scope,
                resource=resource,
                object_id=object_id,
                object_name=object_name,
                current=_resolved_level(
                    current, _deciding_subject_name(subject.access, current, role_names, member_names)
                ),
                proposed=_resolved_level(
                    proposed, _deciding_subject_name(subject.access, proposed, role_names, member_names)
                ),
                direction=direction,
            )
        )

    # Resource scope: resources that have resource-level rows. The everyone-subject cannot
    # differ here (only default rows are visible to it, and one tier resolves the same both
    # ways), so only named subjects with a row on the resource are compared.
    resource_rows: dict[str, list[AccessControl]] = {}
    for row in rows:
        if row.resource_id is None and row.resource not in RESOURCES_WITHOUT_RESOURCE_LEVEL_CONTROLS:
            resource_rows.setdefault(row.resource, []).append(row)
    for resource, pool in resource_rows.items():
        relevant = _relevant_subject_keys(pool)
        for subject in subjects:
            if subject.ref.type == "everyone" or (subject.ref.type, subject.ref.id) not in relevant:
                continue
            compare(
                subject,
                "resource",
                resource,
                subject.access.access_level_for_resource(cast(APIScopeObject, resource)),
                subject.access.resolve_most_specific_resource_access(cast(APIScopeObject, resource)),
            )

    # Object scope: objects that have rules. A subject is compared only against objects of a
    # resource it has any row for, which keeps the pair count near the rule count instead of
    # subjects x objects.
    object_ids_by_resource: dict[str, list[str]] = {}
    for row in rows:
        if row.resource_id is not None:
            ids = object_ids_by_resource.setdefault(row.resource, [])
            if row.resource_id not in ids:
                ids.append(row.resource_id)
    rows_by_resource: dict[str, list[AccessControl]] = {}
    for row in rows:
        rows_by_resource.setdefault(row.resource, []).append(row)

    for resource, object_ids in object_ids_by_resource.items():
        objects = _load_objects(team, resource, object_ids)
        relevant = _relevant_subject_keys(rows_by_resource.get(resource, []))
        relevant.add(("everyone",))  # the object default vs resource level case names no subject
        for subject in subjects:
            key = ("everyone",) if subject.ref.type == "everyone" else (subject.ref.type, subject.ref.id)
            if key not in relevant:
                continue
            for object_id in object_ids:
                loaded = objects.get(object_id)
                if loaded is None:
                    continue
                obj, object_name = loaded
                if subject.member_user_id is not None and getattr(obj, "created_by_id", None) == subject.member_user_id:
                    # Creators keep the highest level under both ladders
                    continue
                compare(
                    subject,
                    "object",
                    resource,
                    _enforced_object_access(subject.access, obj, cast(APIScopeObject, resource)),
                    subject.access.resolve_most_specific_object_access(obj),
                    object_id=object_id,
                    object_name=object_name,
                )

    return changes
