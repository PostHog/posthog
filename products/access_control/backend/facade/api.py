"""
Facade API for access_control.

This is the module that other apps / the presentation layer should
import from. It accepts plain inputs and returns contract DTOs, never
ORM instances or QuerySets.

Responsibilities:
- Accept DTOs / primitive inputs
- Call domain logic / ORM
- Convert Django models to DTOs before returning
- Remain thin and stable

Do NOT:
- Import DRF / serializers / HTTP concerns here
- Return ORM instances or QuerySets
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from copy import copy
from typing import Any, cast
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_delete, post_save, pre_delete
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from posthog.hogql.property_access_types import RestrictedProperty

from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.models import Organization, OrganizationMembership, Team
from posthog.models.activity_logging.activity_log import LogActivityEntry, bulk_log_activity
from posthog.models.activity_logging.model_activity import get_current_user, get_was_impersonated
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.user import User
from posthog.scopes import API_SCOPE_OBJECTS, INTERNAL_API_SCOPE_OBJECTS, APIScopeObject

from products.access_control.backend.activity_logging import get_access_control_log_entry
from products.access_control.backend.models.role import Role, RoleMembership
from products.event_definitions.backend.models import PropertyDefinition, effective_project_id_expr

from ..models.access_control import AccessControl
from ..models.property_access_control import PropertyAccessControl
from ..models.team_access_control_config import TeamAccessControlConfig
from ..property_access_control import (
    get_non_writable_property_names as _get_non_writable_property_names,
    get_restricted_properties_with_group_type_index_for_team as _get_restricted_properties_with_group_type_index_for_team,
    is_property_access_control_enabled,
)
from . import contracts
from .contracts import PropertyAccessLevel
from .enums import AI_EVENT_PROPERTY_CHOICES
from .user_access_control import (
    ACCESS_CONTROL_MAX_OBJECTS_PER_RESOURCE,
    RESOURCE_INHERITANCE_MAP,
    RESOURCES_WITHOUT_RESOURCE_LEVEL_CONTROLS,
    AccessControlLevel,
    access_level_satisfied_for_resource,
    default_access_level,
    highest_access_level,
    minimum_access_level,
    ordered_access_levels,
)


class InvalidObjectAccessControlError(Exception):
    """Raised when an object access control rule names an unknown resource, an access level the
    resource does not support, or a subject outside the team's organization."""


class PropertyDefinitionNotFoundError(Exception):
    """Raised when the target property definition cannot be found for the team."""


class PropertyAccessControlRuleNotFoundError(Exception):
    """Raised when trying to delete a rule that does not exist."""


class InvalidPropertyAccessControlTargetError(Exception):
    """Raised when the rule target (role or organization member) does not
    belong to the same organization as the team."""


# --- Mappers (model -> DTO) ---


def _to_rule(rule: PropertyAccessControl) -> contracts.PropertyAccessControlRule:
    # The FK is nullable in the schema, but a rule is always attached to a property: the upsert
    # resolves a concrete definition before writing, and every read path filters null rows out
    assert rule.property_definition_id is not None
    return contracts.PropertyAccessControlRule(
        id=rule.id,
        property_definition_id=rule.property_definition_id,
        access_level=PropertyAccessLevel(rule.access_level),
        organization_member_id=rule.organization_member_id,
        role_id=rule.role_id,
        created_by_id=rule.created_by_id,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def get_property_definition_labels(
    *, team_id: int, property_definition_ids: list[UUID]
) -> dict[UUID, contracts.PropertyDefinitionLabel]:
    return {
        definition.id: contracts.PropertyDefinitionLabel(
            id=definition.id,
            name=definition.name,
            is_person=definition.type == PropertyDefinition.Type.PERSON,
        )
        for definition in PropertyDefinition.objects.filter(team_id=team_id, id__in=property_definition_ids)
    }


def _get_property_definition(property_definition_id: str, team_id: int) -> PropertyDefinition:
    # Callers often send the property name. The pk is a UUID, and Django raises its own
    # ValidationError for any other string, which the API would turn into a 500.
    try:
        UUID(str(property_definition_id))
    except ValueError as exc:
        raise PropertyDefinitionNotFoundError(property_definition_id) from exc
    project_id = Team.objects.values_list("project_id", flat=True).get(id=team_id)
    try:
        return get_object_or_404(
            PropertyDefinition.objects.alias(effective_project_id=effective_project_id_expr()),
            effective_project_id=project_id,
            id=property_definition_id,
        )
    except Http404 as exc:
        # Normalize 404 -> domain error so presentation can translate without leaking ORM concerns.
        raise PropertyDefinitionNotFoundError(property_definition_id) from exc


# --- Read API ---


def get_restricted_properties_with_group_type_index_for_team(
    *, user: User | None, team_id: int
) -> set[RestrictedProperty]:
    """Return property restrictions for a user and team."""
    return _get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team_id)


def get_restricted_properties_for_group_type(
    *, user: User | None, team_id: int, group_type_index: int
) -> set[RestrictedProperty]:
    """Return property restrictions for a query over one group type, leaving out other group types' restrictions."""
    return {
        restriction
        for restriction in _get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team_id)
        if restriction.property_type != PropertyDefinition.Type.GROUP
        or restriction.group_type_index in (None, group_type_index)
    }


def split_restricted_property_names(restrictions: set[RestrictedProperty]) -> contracts.RestrictedPropertyNames:
    """Return restricted event, person, and group property names."""
    group: defaultdict[int | None, set[str]] = defaultdict(set)
    for restriction in restrictions:
        if restriction.property_type == PropertyDefinition.Type.GROUP:
            group[restriction.group_type_index].add(restriction.name)
    return contracts.RestrictedPropertyNames(
        event=frozenset(
            restriction.name
            for restriction in restrictions
            if restriction.property_type == PropertyDefinition.Type.EVENT
        ),
        person=frozenset(
            restriction.name
            for restriction in restrictions
            if restriction.property_type == PropertyDefinition.Type.PERSON
        ),
        group={group_type_index: frozenset(names) for group_type_index, names in group.items()},
    )


def get_restricted_group_property_names_by_type_index(
    *, user: User | None, team_id: int
) -> dict[int | None, frozenset[str]]:
    """Return restricted group property names keyed by group type index (None applies to every group type)."""
    names_by_index: dict[int | None, set[str]] = defaultdict(set)
    for restriction in _get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team_id):
        if restriction.property_type == PropertyDefinition.Type.GROUP:
            names_by_index[restriction.group_type_index].add(restriction.name)
    return {index: frozenset(names) for index, names in names_by_index.items()}


def get_non_writable_group_property_names(*, user: User | None, team_id: int, group_type_index: int) -> frozenset[str]:
    """Return group property names of this group type that the user cannot write."""
    return frozenset(
        _get_non_writable_property_names(
            team_id=team_id,
            user=user,
            property_type=PropertyDefinition.Type.GROUP,
            group_type_index=group_type_index,
        )
    )


def get_property_access_state(
    *,
    team_id: int,
    property_definition_id: str,
) -> contracts.PropertyAccessControlState:
    """Return the full access-control state for a single property definition."""
    prop_def = _get_property_definition(property_definition_id, team_id)

    rules_qs = PropertyAccessControl.objects.filter(
        team_id=team_id,
        property_definition=prop_def,
    ).select_related("organization_member", "role", "created_by")
    rules = list(rules_qs)

    # The rule with null membership AND null role acts as the property-level default.
    default_rule = next(
        (r for r in rules if r.organization_member_id is None and r.role_id is None),
        None,
    )
    default_level = PropertyAccessLevel(default_rule.access_level) if default_rule else PropertyAccessLevel.READ_WRITE

    return contracts.PropertyAccessControlState(
        rules=[_to_rule(r) for r in rules],
        available_access_levels=list(PropertyAccessLevel),
        default_access_level=default_level,
    )


def list_property_access_controls(
    *,
    team_id: int,
    organization_member_id: UUID | None = None,
    role_id: UUID | None = None,
) -> list[contracts.PropertyAccessControlRule]:
    """All property rules belonging to one subject: a member, a role, or (both None) the project-wide default."""
    rules = PropertyAccessControl.objects.filter(
        team_id=team_id,
        organization_member_id=organization_member_id,
        role_id=role_id,  # type: ignore
        property_definition__isnull=False,
    )
    return [_to_rule(rule) for rule in rules]


def team_has_property_access_rules(*, team_id: int) -> bool:
    """Whether the team has any property-level access-control rules in effect.

    True only when the feature is available for the org AND at least one rule
    targeting a property definition exists. Callers that share results across
    users (e.g. userless precompute) use this to opt out entirely, since a
    result computed without a user cannot honor per-user property restrictions.
    """
    if not is_property_access_control_enabled(team_id=team_id):
        return False
    return PropertyAccessControl.objects.filter(team_id=team_id, property_definition__isnull=False).exists()


def person_property_names_with_access_rules(*, team_id: int) -> frozenset[str]:
    """Person properties with any access rule on the team, for callers that share a result across users."""
    return frozenset(
        PropertyAccessControl.objects.filter(
            team_id=team_id, property_definition__type=PropertyDefinition.Type.PERSON
        ).values_list("property_definition__name", flat=True)
    )


def group_property_names_with_access_rules(*, team_id: int, group_type_index: int) -> frozenset[str]:
    """Group properties of one group type with any access rule on the team, for callers that share a result across users."""
    return frozenset(
        PropertyAccessControl.objects.filter(
            team_id=team_id,
            property_definition__type=PropertyDefinition.Type.GROUP,
            property_definition__group_type_index=group_type_index,
        ).values_list("property_definition__name", flat=True)
    )


def property_key_overlaps_restriction(key: str, restricted_names: Collection[str]) -> bool:
    """Whether a top-level property key is restricted, sits under a restricted name, or holds one inside its value.

    Names are dot paths, as HogQL reads them: a rule on `a.b` covers the flat key `a.b` and the child `b` of `a`.
    """
    segments = key.split(".")
    for name in restricted_names:
        name_segments = name.split(".")
        shared = min(len(segments), len(name_segments))
        if segments[:shared] == name_segments[:shared]:
            return True
    return False


def redact_restricted_properties(properties: Mapping[str, Any], restricted_names: Collection[str]) -> dict[str, Any]:
    """Drop restricted properties, following dot paths into nested objects and arrays the way HogQL masks them."""
    return _redact_object(properties, restricted_names)


def _redact_object(properties: Mapping[str, Any], restricted_names: Collection[str]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in properties.items():
        if any(key == name or key.startswith(f"{name}.") for name in restricted_names):
            continue
        children = [name[len(key) + 1 :] for name in restricted_names if name.startswith(f"{key}.")]
        redacted[key] = _redact_value(value, children) if children else value
    return redacted


def _redact_value(value: Any, restricted_names: Collection[str]) -> Any:
    if isinstance(value, Mapping):
        return _redact_object(value, restricted_names)
    if isinstance(value, list):
        return [_redact_value(item, restricted_names) for item in value]
    return value


def team_has_public_sharing_access_rules(*, team_id: int) -> bool:
    return (
        AccessControl.objects.filter(
            team_id=team_id,
            resource__in=[
                "project",
                "dashboard",
                "notebook",
                "insight",
                "external_data_source",
                "warehouse_objects",
                "warehouse_table",
                "warehouse_view",
            ],
        ).exists()
        or PropertyAccessControl.objects.filter(team_id=team_id, property_definition__isnull=False).exists()
    )


def user_organizations_use_access_controls(*, user_id: int) -> bool:
    """Whether access rules can narrow what the user reaches in one of their organizations.

    True only when an organization the user belongs to has the access-control feature AND
    at least one rule exists in one of its projects.
    """
    entitled = [
        org.id
        for org in Organization.objects.filter(members=user_id)
        if org.is_feature_available(AvailableFeature.ACCESS_CONTROL)
    ]
    if not entitled:
        return False
    return AccessControl.objects.filter(team__organization_id__in=entitled).exists()


def can_write_access_rules(*, team_id: int, user_id: int) -> bool:
    """True when the lock is disabled, or when the user is the Terraform account. An enabled lock
    with no account refuses everyone until the first Terraform write. The check is on the user
    behind the request and never on a client header, because any client can send any header."""
    config = TeamAccessControlConfig.objects.filter(team_id=team_id, is_managed_by_terraform=True).first()
    if config is None:
        return True
    return config.terraform_managed_by is not None and config.terraform_managed_by.user_id == user_id


def can_delete_role(*, role_id: UUID, user_id: int) -> bool:
    """False when the role has rules in a project that Terraform manages and the user is not the
    Terraform account. AccessControl.role cascades, so the delete would remove those rules without
    any rule endpoint running."""
    return not (
        TeamAccessControlConfig.objects.filter(
            is_managed_by_terraform=True,
            team_id__in=AccessControl.objects.filter(role_id=role_id).values("team_id"),
        )
        .exclude(terraform_managed_by__user_id=user_id)
        .exists()
    )


def get_terraform_lock(*, team_id: int) -> contracts.TerraformLock:
    config = TeamAccessControlConfig.objects.filter(team_id=team_id).first()
    return contracts.TerraformLock(
        managed=config is not None and config.is_managed_by_terraform,
        terraform_last_applied_at=config.terraform_last_applied_at if config else None,
        has_terraform_account=config is not None and config.terraform_managed_by_id is not None,
    )


def set_terraform_lock(*, team_id: int, enabled: bool, terraform_user_id: int | None = None) -> contracts.TerraformLock:
    """Enable or disable the lock.

    With terraform_user_id, a Terraform write made the call. The owner of that API key becomes the
    Terraform account of the project, and the write time is recorded. A different account replaces
    the stored one, so a rotated service account continues to work.

    Without terraform_user_id, an admin made the call. Disable keeps the account. Enable before the
    first Terraform write locks everyone out until that write."""
    team = get_object_or_404(Team, id=team_id)
    config = get_or_create_team_extension(team, TeamAccessControlConfig)
    if terraform_user_id is not None:
        membership = OrganizationMembership.objects.filter(
            organization_id=team.organization_id, user_id=terraform_user_id
        ).first()
        if membership is not None:
            config.terraform_managed_by = membership
        config.terraform_last_applied_at = timezone.now()
    config.is_managed_by_terraform = enabled
    config.save(update_fields=["terraform_managed_by", "terraform_last_applied_at", "is_managed_by_terraform"])
    return get_terraform_lock(team_id=team_id)


def _level_rank(levels: list[AccessControlLevel], level: str) -> int:
    """Position of `level` on the ladder, with an unrecognized level ranked below every real one."""
    return levels.index(cast(AccessControlLevel, level)) if level in levels else -1


def _grants_at_least(resource: APIScopeObject, level: str, required_level: AccessControlLevel) -> bool:
    """Whether `level` satisfies `required_level`, reading an unrecognized level as no grant.

    The access level of a row is an unvalidated string, so a value outside the ladder of the
    resource is possible. Comparing it would raise, so treat it as restricting instead."""
    if level not in ordered_access_levels(resource):
        return False
    return access_level_satisfied_for_resource(resource, cast(AccessControlLevel, level), required_level)


def every_member_has_resource_access(
    *, team_id: int, resource: APIScopeObject, required_level: AccessControlLevel
) -> bool:
    """Whether every member of the team resolves at least `required_level` on `resource`.

    For a caller that builds something without a request user and hands it to many readers at
    once — an AI-drafted ticket note, a userless precompute. Such a caller cannot honor a
    restriction on one member, so it asks whether any restriction exists at all and leaves the
    data out when one does.

    Deliberately conservative, and for that reason the same answer under both resolution orders:
    one restricting rule makes this False, including where highest-wins resolution would let a
    permissive default outrank it. Erring toward withholding keeps the answer stable when an
    organization moves to most-specific resolution.
    """
    team = Team.objects.select_related("organization").filter(id=team_id).first()
    if team is None:
        return False

    # Resolution reads the rows of the parent of an inheriting resource, never the child's own
    # resource-scope rows, so the parent is what to inspect.
    resource = RESOURCE_INHERITANCE_MAP.get(resource, resource)

    # With no rules in effect, every member sits at the built-in default for the resource.
    if resource in RESOURCES_WITHOUT_RESOURCE_LEVEL_CONTROLS or not team.organization.is_feature_available(
        AvailableFeature.ACCESS_CONTROL
    ):
        return _grants_at_least(resource, default_access_level(resource), required_level)

    rows = list(AccessControl.objects.filter(team_id=team_id, resource=resource, resource_id=None))
    everyone_rows = [row for row in rows if row.organization_member_id is None and row.role_id is None]
    subject_rows = [row for row in rows if row.organization_member_id is not None or row.role_id is not None]

    levels = ordered_access_levels(resource)
    floor = (
        max((row.access_level for row in everyone_rows), key=lambda level: _level_rank(levels, level))
        if everyone_rows
        else default_access_level(resource)
    )
    if not _grants_at_least(resource, floor, required_level):
        return False
    return all(_grants_at_least(resource, row.access_level, required_level) for row in subject_rows)


def object_ids_restricted_from_any_member(
    *, team_id: int, resource: APIScopeObject, required_level: AccessControlLevel
) -> set[str]:
    """Ids of `resource` objects carrying a rule that gives somebody less than `required_level`.

    The object-level counterpart of `every_member_has_resource_access`, for the same kind of
    caller: one that builds something without a request user and hands it to many readers at
    once. It cannot tell those readers apart, so it leaves out every object that any rule
    withholds from any of them.

    Conservative in the same way. One restricting rule on an object is enough to name it, even
    where resolution would let a permissive rule outrank that one, so the answer does not change
    when an organization moves to most-specific resolution.
    """
    team = Team.objects.select_related("organization").filter(id=team_id).first()
    if team is None or not team.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
        return set()

    # Object rows are written against the resource itself, never its parent, so an inheriting
    # resource is not mapped here the way a resource-scope lookup maps it.
    satisfying = [
        level for level in ordered_access_levels(resource) if _grants_at_least(resource, level, required_level)
    ]
    restricted = (
        AccessControl.objects.filter(team_id=team_id, resource=resource, resource_id__isnull=False)
        .exclude(access_level__in=satisfying)
        .values_list("resource_id", flat=True)
    )
    return {resource_id for resource_id in restricted if resource_id}


def object_ids_with_rules(*, team_id: int, resource: APIScopeObject) -> set[str]:
    """Ids of `resource` objects that carry any object-level rule, whatever its level.

    For a caller that copies an object into a new one that can't carry the same rules. It skips
    every object with a rule rather than judging which rules restrict, and it ignores whether
    the organization enforces rules today, because the rules apply again when it does.
    """
    resource_ids = AccessControl.objects.filter(
        team_id=team_id, resource=resource, resource_id__isnull=False
    ).values_list("resource_id", flat=True)
    return {resource_id for resource_id in resource_ids if resource_id}


def resource_has_rules(*, team_id: int, resource: APIScopeObject) -> bool:
    """Whether the team has any resource-level rule for `resource`, whatever its level.

    For a caller about to make objects inherit from `resource`, which changes what those rules
    reach. Like `object_ids_with_rules`, it ignores whether the organization enforces rules today.
    """
    return AccessControl.objects.filter(team_id=team_id, resource=resource, resource_id__isnull=True).exists()


def access_rules(*, team_id: int, resources: Collection[str]) -> list[contracts.AccessRule]:
    """Every rule of the team on these resources, object-level and resource-level, whatever its level.

    For a caller that must predict what resolution decides after it changes which rules reach an
    object. Like `object_ids_with_rules`, it ignores whether the organization enforces rules today,
    because the rules apply again when it does.
    """
    team = Team.objects.only("id", "organization_id").get(id=team_id)
    rows = AccessControl.objects.filter(team_id=team_id, resource__in=list(resources)).values_list(
        "resource",
        "resource_id",
        "access_level",
        "organization_member_id",
        "role_id",
        "organization_member__organization_id",
        "role__organization_id",
    )
    return [
        contracts.AccessRule(
            resource=resource,
            resource_id=resource_id,
            access_level=access_level,
            organization_member_id=member_id,
            role_id=role_id,
            # Resolution reads a member's rules only in the member's own organization, and a role's
            # rules only for a role of that organization (see UserAccessControl._filter_options).
            applies=(member_id is None or role_id is None)
            and (member_id is None or member_organization_id == team.organization_id)
            and (role_id is None or role_organization_id == team.organization_id),
        )
        for (
            resource,
            resource_id,
            access_level,
            member_id,
            role_id,
            member_organization_id,
            role_organization_id,
        ) in rows
    ]


def replace_object_access_rules(
    *, team_id: int, resource: str, resource_id: str, rules: Sequence[contracts.ObjectAccessRuleInput]
) -> None:
    """Make the rules on one object exactly `rules`, the object's default rule included.

    A rule that is already there stays. The others are created or deleted one at a time, so each
    change goes into the activity log. An empty `rules` removes every rule on the object. The
    caller decides whether the change is allowed.
    """
    team = Team.objects.only("id", "organization_id").get(id=team_id)
    wanted: dict[tuple[UUID | None, UUID | None], str] = {}
    for rule in rules:
        _validate_resource_access_level(resource, rule.access_level)
        key = (rule.organization_member_id, rule.role_id)
        if key in wanted:
            raise InvalidObjectAccessControlError("Provide each subject only once.")
        wanted[key] = rule.access_level
    member_ids = {member_id for member_id, _ in wanted if member_id is not None}
    role_ids = {role_id for _, role_id in wanted if role_id is not None}
    if member_ids != set(
        OrganizationMembership.objects.filter(organization_id=team.organization_id, id__in=member_ids).values_list(
            "id", flat=True
        )
    ):
        raise InvalidObjectAccessControlError("organization_member does not belong to this team's organization.")
    if role_ids != set(
        Role.objects.filter(organization_id=team.organization_id, id__in=role_ids).values_list("id", flat=True)
    ):
        raise InvalidObjectAccessControlError("role does not belong to this team's organization.")

    with transaction.atomic():
        kept: set[tuple[UUID | None, UUID | None]] = set()
        for existing in AccessControl.objects.select_for_update().filter(
            team_id=team_id, resource=resource, resource_id=resource_id
        ):
            key = (existing.organization_member_id, existing.role_id)
            if key not in kept and wanted.get(key) == existing.access_level:
                kept.add(key)
            else:
                existing.delete()
        for (member_id, role_id), access_level in wanted.items():
            if (member_id, role_id) not in kept:
                AccessControl.objects.create(
                    team_id=team_id,
                    resource=resource,
                    resource_id=resource_id,
                    access_level=access_level,
                    organization_member_id=member_id,
                    role_id=role_id,
                )


def object_has_access_rules(*, team_id: int, resource: str, resource_id: str) -> bool:
    """Whether the object has access rules of its own, as opposed to only the rules it inherits."""
    return AccessControl.objects.filter(team_id=team_id, resource=resource, resource_id=resource_id).exists()


def _copyable_object_rules(team_id: int, resource: str, resource_id: str) -> list[contracts.ObjectAccessRuleInput]:
    # Rules naming a member or role of another organization never apply, so they are not copied.
    team = Team.objects.only("id", "organization_id").get(id=team_id)
    return [
        contracts.ObjectAccessRuleInput(
            access_level=rule.access_level,
            organization_member_id=rule.organization_member_id,
            role_id=rule.role_id,
        )
        for rule in AccessControl.objects.filter(team_id=team_id, resource=resource, resource_id=resource_id)
        .filter(Q(organization_member__isnull=True) | Q(organization_member__organization_id=team.organization_id))
        .filter(Q(role__isnull=True) | Q(role__organization_id=team.organization_id))
    ]


def check_object_access_rules_copy(
    *, team_id: int, resource: str, from_resource_id: str, to_resource_id: str | None
) -> None:
    """Raise `InvalidObjectAccessControlError` when copying the rules of one object to another would pass
    the cap the rule endpoint applies when a rule is first set on an object.

    `to_resource_id` is None for an object that doesn't exist yet, which has no rules.
    """
    if not AccessControl.objects.filter(team_id=team_id, resource=resource, resource_id=from_resource_id).exists():
        return
    if (
        to_resource_id is not None
        and AccessControl.objects.filter(team_id=team_id, resource=resource, resource_id=to_resource_id).exists()
    ):
        return
    objects_with_rules = (
        AccessControl.objects.filter(team_id=team_id, resource=resource, resource_id__isnull=False)
        .values("resource_id")
        .distinct()
        .count()
    )
    if objects_with_rules >= ACCESS_CONTROL_MAX_OBJECTS_PER_RESOURCE:
        raise InvalidObjectAccessControlError(
            f"Reached the limit of {ACCESS_CONTROL_MAX_OBJECTS_PER_RESOURCE} {resource}s with access control overrides."
        )


def copy_object_access_rules(*, team_id: int, resource: str, from_resource_id: str, to_resource_id: str) -> None:
    """Make the rules on one object the same as the rules on another object of the same resource.

    Replaces every rule the target has, through `replace_object_access_rules`, so each change goes
    into the activity log. The caller decides whether the change is allowed.
    """
    check_object_access_rules_copy(
        team_id=team_id, resource=resource, from_resource_id=from_resource_id, to_resource_id=to_resource_id
    )
    replace_object_access_rules(
        team_id=team_id,
        resource=resource,
        resource_id=to_resource_id,
        rules=_copyable_object_rules(team_id, resource, from_resource_id),
    )


def role_belongs_to_organization(*, role_id: str | UUID, organization_id: UUID) -> bool:
    """Whether the role is a role of that organization.

    For a caller that accepts a role id from a request and must not let it name a role of
    another organization.
    """
    return Role.objects.filter(id=role_id, organization_id=organization_id).exists()


def organization_role_names(*, organization_id: UUID, role_ids: Collection[UUID]) -> dict[UUID, str]:
    """Names of the given roles, keyed by id. A role of another organization is left out."""
    return dict(Role.objects.filter(organization_id=organization_id, id__in=role_ids).values_list("id", "name"))


def valid_role_member_user_ids(*, role_id: str | UUID) -> list[int]:
    """Ids of the users the role grants access to.

    A membership whose organization member moved to another organization no longer grants
    anything, so it is left out.
    """
    return list(
        RoleMembership.objects.filter(role_id=role_id).valid_for_authorization().values_list("user_id", flat=True)
    )


# --- Write API ---


def _get_or_create_ai_property_definition(team_id: int, property_name: str) -> PropertyDefinition:
    project_id = Team.objects.values_list("project_id", flat=True).get(id=team_id)
    project_definitions = PropertyDefinition.objects.alias(effective_project_id=effective_project_id_expr()).filter(
        effective_project_id=project_id
    )
    definition, _ = project_definitions.get_or_create(
        name=property_name,
        type=PropertyDefinition.Type.EVENT,
        group_type_index=None,
        defaults={"team_id": team_id, "project_id": project_id},
    )
    return definition


def _validate_target_org(
    *,
    team_id: int,
    organization_member_id: UUID | None,
    role_id: UUID | None,
) -> None:
    """Ensure the rule target (role / organization member) belongs to the
    team's organization.

    Without this check, an org admin who is also a member of another
    organization could inject role or membership UUIDs from that other org
    into rules here — which would then either be silently inert or, worse,
    collide with intra-org IDs in audits and downstream logic.
    """
    if organization_member_id is None and role_id is None:
        return

    organization_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        # Team doesn't exist — the upstream get_object lookup would have failed already,
        # but be defensive.
        raise InvalidPropertyAccessControlTargetError("Team not found.")

    if organization_member_id is not None:
        if not OrganizationMembership.objects.filter(
            id=organization_member_id, organization_id=organization_id
        ).exists():
            raise InvalidPropertyAccessControlTargetError(
                "organization_member does not belong to this team's organization."
            )

    if role_id is not None:
        if not Role.objects.filter(id=role_id, organization_id=organization_id).exists():
            raise InvalidPropertyAccessControlTargetError("role does not belong to this team's organization.")


def upsert_property_access_control(
    *,
    team_id: int,
    created_by_id: int | None,
    input: contracts.UpsertPropertyAccessControlInput,
) -> contracts.PropertyAccessControlRule:
    """Create or update a single access control rule."""
    if input.ai_property is not None and input.ai_property not in AI_EVENT_PROPERTY_CHOICES:
        raise InvalidPropertyAccessControlTargetError("Unknown AI event property.")
    _validate_target_org(
        team_id=team_id,
        organization_member_id=input.organization_member_id,
        role_id=input.role_id,
    )

    with transaction.atomic():
        if input.ai_property is not None:
            prop_def = _get_or_create_ai_property_definition(team_id, input.ai_property)
        else:
            assert input.property_definition_id is not None
            prop_def = _get_property_definition(input.property_definition_id, team_id)

        # `created_by_id` must only be set on creation — using `defaults` would
        # overwrite the original creator on every update. `create_defaults`
        # (Django 4.2+) is applied only when a new row is inserted.
        rule, _created = PropertyAccessControl.objects.update_or_create(
            team_id=team_id,
            property_definition=prop_def,
            organization_member_id=input.organization_member_id,
            role_id=input.role_id,  # type: ignore[misc]  # nullable FK; django-stubs drops None from *_id lookups
            defaults={
                "access_level": input.access_level.value,
            },
            create_defaults={
                "access_level": input.access_level.value,
                "created_by_id": created_by_id,
            },
        )
    return _to_rule(rule)


def delete_property_access_control(
    *,
    team_id: int,
    input: contracts.DeletePropertyAccessControlInput,
) -> None:
    """Delete an override rule. Raises PropertyAccessControlRuleNotFoundError if nothing matched."""
    prop_def = _get_property_definition(input.property_definition_id, team_id)
    _validate_target_org(
        team_id=team_id,
        organization_member_id=input.organization_member_id,
        role_id=input.role_id,
    )

    deleted, _ = PropertyAccessControl.objects.filter(
        team_id=team_id,
        property_definition=prop_def,
        organization_member_id=input.organization_member_id,
        role_id=input.role_id,  # type: ignore
    ).delete()
    if not deleted:
        raise PropertyAccessControlRuleNotFoundError


# --- Object access controls ---


def _to_object_rule(rule: AccessControl) -> contracts.ObjectAccessControlRule:
    assert rule.resource_id is not None
    return contracts.ObjectAccessControlRule(
        id=rule.id,
        resource=rule.resource,
        resource_id=rule.resource_id,
        access_level=rule.access_level,
        organization_member_id=rule.organization_member_id,
        role_id=rule.role_id,
    )


def _validate_object_access_control_level(input: contracts.SetObjectAccessControlInput) -> APIScopeObject:
    return _validate_resource_access_level(input.resource, input.access_level)


def _validate_resource_access_level(resource: str, access_level: str | None) -> APIScopeObject:
    if resource not in API_SCOPE_OBJECTS or resource in INTERNAL_API_SCOPE_OBJECTS:
        raise InvalidObjectAccessControlError(f"{resource} is not an access controlled resource.")
    scoped_resource = cast(APIScopeObject, resource)

    if access_level is not None:
        levels = ordered_access_levels(scoped_resource)
        if access_level not in levels:
            raise InvalidObjectAccessControlError(
                f"Invalid access level for {resource}. Must be one of: {', '.join(levels)}."
            )
        # `ordered_access_levels` can include levels the settings UI never offers for a resource
        # (for example "none" on a project), so the bounds apply here as well as in the API.
        level_index = levels.index(cast(AccessControlLevel, access_level))
        if level_index < levels.index(minimum_access_level(scoped_resource)):
            raise InvalidObjectAccessControlError(f"Access level is below the minimum for {resource}.")
        if level_index > levels.index(highest_access_level(scoped_resource)):
            raise InvalidObjectAccessControlError(f"Access level is above the maximum for {resource}.")

    return scoped_resource


def _validate_object_access_control(
    *, organization_id: UUID, input: contracts.SetObjectAccessControlInput
) -> APIScopeObject:
    resource = _validate_object_access_control_level(input)
    if (
        input.organization_member_id is not None
        and not OrganizationMembership.objects.filter(
            id=input.organization_member_id, organization_id=organization_id
        ).exists()
    ):
        raise InvalidObjectAccessControlError("organization_member does not belong to this team's organization.")
    if (
        input.role_id is not None
        and not Role.objects.filter(id=input.role_id, organization_id=organization_id).exists()
    ):
        raise InvalidObjectAccessControlError("role does not belong to this team's organization.")
    return resource


@frozen
class _ObjectAccessControlKey:
    resource: str
    resource_id: str | None
    organization_member_id: UUID | None
    role_id: UUID | None


def _object_access_control_key(
    rule: contracts.SetObjectAccessControlInput | AccessControl,
) -> _ObjectAccessControlKey:
    return _ObjectAccessControlKey(
        resource=rule.resource,
        resource_id=rule.resource_id,
        organization_member_id=rule.organization_member_id,
        role_id=rule.role_id,
    )


def bulk_set_object_access_controls(*, team_id: int, inputs: list[contracts.SetObjectAccessControlInput]) -> None:
    if not inputs:
        return
    team = Team.objects.only("id", "organization_id").get(id=team_id)
    requested = {_object_access_control_key(input): input for input in inputs}
    if len(requested) != len(inputs):
        raise InvalidObjectAccessControlError("Provide each object and subject only once.")
    for input in inputs:
        _validate_object_access_control_level(input)
    member_ids = {input.organization_member_id for input in inputs if input.organization_member_id is not None}
    role_ids = {input.role_id for input in inputs if input.role_id is not None}
    if member_ids != set(
        OrganizationMembership.objects.filter(organization_id=team.organization_id, id__in=member_ids).values_list(
            "id", flat=True
        )
    ):
        raise InvalidObjectAccessControlError("organization_member does not belong to this team's organization.")
    if role_ids != set(
        Role.objects.filter(organization_id=team.organization_id, id__in=role_ids).values_list("id", flat=True)
    ):
        raise InvalidObjectAccessControlError("role does not belong to this team's organization.")

    requested_pairs = Q()
    for key in requested:
        requested_pairs |= Q(
            resource=key.resource,
            resource_id=key.resource_id,
            organization_member_id=key.organization_member_id,
            role_id=key.role_id,
        )
    with transaction.atomic():
        existing: dict[_ObjectAccessControlKey, list[AccessControl]] = defaultdict(list)
        for existing_rule in (
            AccessControl.objects.select_for_update().filter(requested_pairs, team_id=team_id).order_by("id")
        ):
            existing[_object_access_control_key(existing_rule)].append(existing_rule)
        created: list[AccessControl] = []
        updated: list[AccessControl] = []
        deleted_ids: list[UUID] = []
        entries: list[LogActivityEntry] = []
        now = timezone.now()
        for key, input in requested.items():
            matching_rules: list[AccessControl | None] = [*existing.get(key, [])] or [None]
            for rule in matching_rules:
                before = copy(rule) if rule is not None else None
                if before is not None:
                    before.team = team
                if input.access_level is None:
                    if rule is None:
                        continue
                    deleted_ids.append(rule.id)
                    activity = "deleted"
                    rule = None
                elif rule is None:
                    rule = AccessControl(
                        team=team,
                        resource=input.resource,
                        resource_id=input.resource_id,
                        organization_member_id=input.organization_member_id,
                        role_id=input.role_id,
                        access_level=input.access_level,
                        created_by_id=input.created_by_id,
                    )
                    created.append(rule)
                    activity = "created"
                else:
                    if rule.access_level == input.access_level:
                        continue
                    rule.team = team
                    rule.access_level = input.access_level
                    rule.updated_at = now
                    updated.append(rule)
                    activity = "updated"
                entry = get_access_control_log_entry(
                    before_update=before,
                    after_update=rule,
                    activity=activity,
                    user=get_current_user(),
                    was_impersonated=get_was_impersonated(),
                )
                if entry is not None:
                    entries.append(entry)
        AccessControl.objects.bulk_create(created)
        AccessControl.objects.bulk_update(updated, ["access_level", "updated_at"])
        AccessControl.objects.filter(team_id=team_id, id__in=deleted_ids).delete()
        for rule in created:
            post_save.send(sender=AccessControl, instance=rule, created=True)
        for rule in updated:
            post_save.send(sender=AccessControl, instance=rule, created=False)
        bulk_log_activity(entries)


def set_object_access_control(
    *,
    team_id: int,
    input: contracts.SetObjectAccessControlInput,
) -> contracts.ObjectAccessControlRule | None:
    """Grant, change, or remove one subject's access to one object.

    This is the programmatic counterpart of the `PUT .../access_controls` endpoint, for product code
    that must keep a rule in step with its own state (for example, the assignee of a work item).
    It writes the rule only. The caller decides whether the actor may change access, and the
    caller owns the reverse write when its state changes again.

    A `UserAccessControl` built before this call still holds its preloaded rows. Build a new one
    or clear its cache before checking the object again in the same request.

    Returns the stored rule, or None when `access_level` is None and the rule was removed.
    """
    team = Team.objects.only("id", "organization_id").get(id=team_id)
    resource = _validate_object_access_control(organization_id=team.organization_id, input=input)
    if input.access_level is None:
        # Deleted one by one because a queryset delete writes no activity log row.
        for rule in AccessControl.objects.filter(
            team_id=team_id,
            resource=resource,
            resource_id=input.resource_id,
            organization_member_id=input.organization_member_id,
            role_id=cast(UUID | str, input.role_id),
        ):
            rule.delete()
        return None

    rule, _created = AccessControl.objects.update_or_create(
        team_id=team_id,
        resource=resource,
        resource_id=input.resource_id,
        organization_member_id=input.organization_member_id,
        role_id=cast(UUID | str, input.role_id),
        defaults={"access_level": input.access_level},
        create_defaults={"access_level": input.access_level, "created_by_id": input.created_by_id},
    )
    return _to_object_rule(rule)


# --- Convenience for external callers (avoids importing UUID type at call sites) ---


def available_access_levels() -> list[PropertyAccessLevel]:
    return list(PropertyAccessLevel)


_PROPERTY_LEVEL_ORDER = (PropertyAccessLevel.NONE, PropertyAccessLevel.READ, PropertyAccessLevel.READ_WRITE)


def stored_property_rule_floor(*, user: User, team_id: int) -> PropertyAccessLevel | None:
    """The lowest level the stored property rules can give ``user`` on one property of the team.

    The property-rule counterpart of ``UserAccessControl.stored_rule_floor``, with the same
    candidates per property: the user's member rows, else their role rows and the default rows.
    Rows match as ``_resolve_access_level`` matches them: a row naming the user's membership is
    a member row whatever its role, and a row naming one of the user's roles is a role row.
    It holds whether or not the organization is entitled to property access control or roles.
    ``None`` means no stored rule applies. This includes org admins, who bypass property rules.
    """
    organization_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return None
    membership = OrganizationMembership.objects.filter(user=user, organization_id=organization_id).first()
    if membership is None or membership.level >= OrganizationMembership.Level.ADMIN:
        return None
    role_ids = list(
        RoleMembership.objects.filter(user=user, role__organization_id=organization_id)
        .valid_for_authorization()
        .values_list("role_id", flat=True)
    )
    rows = PropertyAccessControl.objects.filter(team_id=team_id, property_definition__isnull=False).filter(
        Q(organization_member=None, role=None) | Q(organization_member_id=membership.id) | Q(role_id__in=role_ids)
    )
    rows_by_property: dict[UUID | None, list[PropertyAccessControl]] = {}
    for row in rows:
        rows_by_property.setdefault(row.property_definition_id, []).append(row)
    lowest: PropertyAccessLevel | None = None
    for property_rows in rows_by_property.values():
        member_rows = [row for row in property_rows if row.organization_member_id == membership.id]
        for row in member_rows or property_rows:
            # A level outside the order is unknown: count it as no access.
            level = next((known for known in _PROPERTY_LEVEL_ORDER if known.value == row.access_level), None)
            level = level or PropertyAccessLevel.NONE
            if lowest is None or _PROPERTY_LEVEL_ORDER.index(level) < _PROPERTY_LEVEL_ORDER.index(lowest):
                lowest = level
    return lowest


def connect_access_change_receivers(
    *,
    on_rule_change: Callable[[int, str], None],
    on_role_membership_change: Callable[[int, UUID], None],
    is_active: Callable[[], bool],
    dispatch_uid: str,
) -> None:
    """Call back when an access rule or a role membership is saved or deleted.

    ``on_rule_change(team_id, resource)`` runs after a rule is saved or deleted. A property rule
    comes in as the ``property_definition`` resource.
    ``on_role_membership_change(user_id, organization_id)`` runs after a role membership is
    saved or deleted. ``organization_id`` is the role's organization, read before a delete while
    the role is still there: most role memberships carry no organization membership.

    Neither runs while ``is_active()`` is false, so a disabled caller costs no role query.

    Both run inside the change's transaction: defer real work with ``transaction.on_commit``.
    Only ids cross this boundary, never the models.
    """

    def rule_changed(sender: object, instance: AccessControl, **kwargs: object) -> None:
        if is_active():
            on_rule_change(instance.team_id, instance.resource)

    def role_membership_changed(sender: object, instance: RoleMembership, **kwargs: object) -> None:
        if is_active():
            on_role_membership_change(instance.user_id, instance.role.organization_id)

    # Outside a transaction a callback's on_commit runs at once, so it must not run before the
    # delete: read the organization before it, and call back after it.
    pending_attr = f"_{dispatch_uid}_role_organization_id"

    def role_membership_deleting(sender: object, instance: RoleMembership, **kwargs: object) -> None:
        if is_active():
            setattr(instance, pending_attr, instance.role.organization_id)

    def role_membership_deleted(sender: object, instance: RoleMembership, **kwargs: object) -> None:
        organization_id = getattr(instance, pending_attr, None)
        if organization_id is not None:
            on_role_membership_change(instance.user_id, organization_id)

    # weak=False: the receivers are closures, and nothing else holds them.
    post_save.connect(rule_changed, sender=AccessControl, weak=False, dispatch_uid=f"{dispatch_uid}_rule_saved")
    post_delete.connect(rule_changed, sender=AccessControl, weak=False, dispatch_uid=f"{dispatch_uid}_rule_deleted")

    def property_rule_changed(sender: object, instance: PropertyAccessControl, **kwargs: object) -> None:
        if is_active():
            on_rule_change(instance.team_id, "property_definition")

    post_save.connect(
        property_rule_changed,
        sender=PropertyAccessControl,
        weak=False,
        dispatch_uid=f"{dispatch_uid}_property_rule_saved",
    )
    post_delete.connect(
        property_rule_changed,
        sender=PropertyAccessControl,
        weak=False,
        dispatch_uid=f"{dispatch_uid}_property_rule_deleted",
    )
    post_save.connect(
        role_membership_changed, sender=RoleMembership, weak=False, dispatch_uid=f"{dispatch_uid}_role_saved"
    )
    pre_delete.connect(
        role_membership_deleting, sender=RoleMembership, weak=False, dispatch_uid=f"{dispatch_uid}_role_deleting"
    )
    post_delete.connect(
        role_membership_deleted, sender=RoleMembership, weak=False, dispatch_uid=f"{dispatch_uid}_role_deleted"
    )


__all__ = [
    "connect_access_change_receivers",
    "stored_property_rule_floor",
    "InvalidPropertyAccessControlTargetError",
    "PropertyAccessControlRuleNotFoundError",
    "PropertyAccessLevel",
    "PropertyDefinitionNotFoundError",
    "available_access_levels",
    "delete_property_access_control",
    "get_property_access_state",
    "list_property_access_controls",
    "upsert_property_access_control",
]
