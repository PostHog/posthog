"""Preview of the most-specific resolution change, per rule subject.

For one team, compare the enforced resolution with the most-specific resolution for every rule
subject (the everyone-default, each named role, each named member) against every object that has
rules and every resource that has resource-level rows. Return one change record per (subject,
scope) pair whose level differs. Members are never enumerated: members with the same applicable
rules resolve identically, so one subject-level record covers all of them.

Read-only. Nothing here changes enforcement. The settings preview page and the divergent-org
sweep command are the only callers.
"""

from collections.abc import Iterator
from dataclasses import replace
from typing import Literal, Optional, cast

from django.db.models import Model

from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.scopes import APIScopeObject

from products.access_control.backend.facade.object_names import display_model, resolve_object_names
from products.access_control.backend.facade.subject_access_control import SubjectAccessControl
from products.access_control.backend.facade.user_access_control import (
    RESOURCE_FALLBACK_MAP,
    RESOURCE_INHERITANCE_MAP,
    RESOURCES_WITHOUT_RESOURCE_LEVEL_CONTROLS,
    ResolvedAccess,
    UserAccessControl,
    ordered_access_levels,
)
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role, RoleMembership

SubjectType = Literal["default", "role", "member"]

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
class ResolutionChange:
    subject: SubjectRef
    scope: Literal["object", "resource"]
    resource: str
    object_id: Optional[str]
    object_name: Optional[str]
    # The object's URL key (e.g. an insight's or notebook's short id) when the model has one,
    # so the page can link to the object
    object_short_id: Optional[str]
    # Both carry subject_name, so the explanation can say which role's grant applies today
    current: ResolvedAccess
    proposed: ResolvedAccess
    direction: Literal["gains", "loses"]


@frozen
class _Subject:
    ref: SubjectRef
    access: SubjectAccessControl
    member_user_id: Optional[int]


@frozen
class _Subjects:
    subjects: list[_Subject]
    role_names: dict[str, str]
    member_names: dict[str, str]


@frozen
class _LoadedObject:
    instance: Model
    name: Optional[str]
    short_id: Optional[str]


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
    return ("default",)


def _build_subjects(team: Team, user_access_control: UserAccessControl, rows: list[AccessControl]) -> _Subjects:
    """One subject per distinct rule target in `rows`, plus the everyone-default, and the
    role and member display names keyed by id.

    Org-admin members are excluded: both resolutions give them the highest level. Role ids of
    each member subject are prefetched here, so subjects do not query per member.
    """
    acting_membership = user_access_control._organization_membership
    if acting_membership is None:
        return _Subjects(subjects=[], role_names={}, member_names={})

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
    ).valid_for_authorization():
        role_ids_by_user.setdefault(rm.user_id, []).append(str(rm.role_id))

    subjects: list[_Subject] = [
        _Subject(
            ref=SubjectRef(type="default", id=None, name="Everyone"),
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
        member_access = SubjectAccessControl(
            user_access_control.user, team, org_membership=acting_membership, member=membership
        )
        subjects.append(
            _Subject(
                ref=SubjectRef(type="member", id=str(membership.id), name=name),
                access=member_access,
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
    return _Subjects(subjects=subjects, role_names=role_names, member_names=member_names)


def _load_objects(team: Team, resource: str, object_ids: list[str]) -> dict[str, _LoadedObject]:
    """Map {object_id -> loaded object} for one resource. Empty when the resource has no
    display model, which also means resolution has no model class to work with."""
    if resource == "project":
        # Project rules point at the team itself
        if str(team.pk) not in object_ids:
            return {}
        return {str(team.pk): _LoadedObject(instance=team, name=team.name, short_id=None)}

    display = display_model(resource)
    if display is None:
        return {}
    names = resolve_object_names(resource, object_ids, team.pk)
    try:
        instances = display.model._base_manager.filter(team_id=team.pk, pk__in=object_ids)
    except Exception as e:
        capture_exception(e, {"resource": resource})
        return {}
    result: dict[str, _LoadedObject] = {}
    for obj in instances:
        object_id = str(obj.pk)
        name = names.get(object_id)
        short_id = getattr(obj, "short_id", None)
        result[object_id] = _LoadedObject(
            instance=obj, name=name.name if name else None, short_id=str(short_id) if short_id else None
        )
    return result


def build_resolution_preview(team: Team, user_access_control: UserAccessControl) -> list[ResolutionChange]:
    """Every (subject, scope) pair on `team` whose enforced and most-specific resolutions differ."""
    if not team.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
        return []

    rows = list(AccessControl.objects.filter(team=team).exclude(resource__in=_SKIPPED_RESOURCES))
    if not rows:
        return []

    subject_index = _build_subjects(team, user_access_control, rows)
    changes: list[ResolutionChange] = []

    def compare(
        subject: _Subject,
        scope: Literal["object", "resource"],
        resource: str,
        current: Optional[ResolvedAccess],
        proposed: Optional[ResolvedAccess],
        object_id: Optional[str] = None,
        object_name: Optional[str] = None,
        object_short_id: Optional[str] = None,
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
                object_short_id=object_short_id,
                current=replace(
                    current,
                    subject_name=_deciding_subject_name(
                        subject.access, current, subject_index.role_names, subject_index.member_names
                    ),
                ),
                proposed=replace(
                    proposed,
                    subject_name=_deciding_subject_name(
                        subject.access, proposed, subject_index.role_names, subject_index.member_names
                    ),
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
        relevant = {_subject_key(row) for row in pool}
        for subject in subject_index.subjects:
            if subject.ref.type == "default" or (subject.ref.type, subject.ref.id) not in relevant:
                continue
            compare(
                subject,
                "resource",
                resource,
                subject.access.access_level_for_resource(cast(APIScopeObject, resource)),
                subject.access.resolve_most_specific_resource_access(cast(APIScopeObject, resource)),
            )

    # Object scope: objects that have rules. A named subject resolves an object differently
    # from the everyone subject only through its explicit rows: on the object itself, at the
    # resource level, or on a parent resource the ladders consult (RESOURCE_INHERITANCE_MAP /
    # RESOURCE_FALLBACK_MAP). Anything narrower drops real changes; anything wider repeats the
    # everyone record once per subject.
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
        explicit_keys_by_object: dict[str, set[tuple]] = {}
        resource_wide_keys: set[tuple] = set()
        for row in rows_by_resource.get(resource, []):
            if _subject_key(row) == ("default",):
                continue
            if row.resource_id is None:
                resource_wide_keys.add(_subject_key(row))
            else:
                explicit_keys_by_object.setdefault(row.resource_id, set()).add(_subject_key(row))
        scoped_resource = cast(APIScopeObject, resource)
        for parent in {RESOURCE_INHERITANCE_MAP.get(scoped_resource), RESOURCE_FALLBACK_MAP.get(scoped_resource)} - {
            None
        }:
            resource_wide_keys |= {
                _subject_key(row)
                for row in rows_by_resource.get(cast(str, parent), [])
                if _subject_key(row) != ("default",)
            }
        for subject in subject_index.subjects:
            key = ("default",) if subject.ref.type == "default" else (subject.ref.type, subject.ref.id)
            # The everyone subject is always compared: the object default vs resource level
            # case names no subject
            subject_is_resource_wide = key == ("default",) or key in resource_wide_keys
            for object_id in object_ids:
                if not subject_is_resource_wide and key not in explicit_keys_by_object.get(object_id, set()):
                    continue
                loaded = objects.get(object_id)
                if loaded is None:
                    continue
                obj = loaded.instance
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
                    object_name=loaded.name,
                    object_short_id=loaded.short_id,
                )

    return changes


def iter_resolution_changes(organization_id: Optional[str] = None) -> "Iterator[tuple[Team, list[ResolutionChange]]]":
    """Yield (team, changes) for every team with access rules, ordered by organization.

    Resolution is evaluated as one acting active member per organization; teams of
    organizations with no active member are skipped.
    """
    team_ids = AccessControl.objects.values_list("team_id", flat=True).distinct()
    teams = Team.objects.filter(id__in=team_ids).select_related("organization").order_by("organization_id")
    if organization_id is not None:
        teams = teams.filter(organization_id=organization_id)

    acting_membership_by_org: dict[str, Optional[OrganizationMembership]] = {}
    for team in teams.iterator():
        org_id = str(team.organization_id)
        if org_id not in acting_membership_by_org:
            acting_membership_by_org[org_id] = (
                OrganizationMembership.objects.filter(organization_id=team.organization_id, user__is_active=True)
                .select_related("user")
                .first()
            )
        membership = acting_membership_by_org[org_id]
        if membership is None:
            continue
        yield team, build_resolution_preview(team, UserAccessControl(membership.user, team))
