import uuid
import itertools
from dataclasses import dataclass
from typing import Optional, cast

import pytest
from posthog.test.base import BaseTest
from unittest import TestCase

from django.apps import apps
from django.db import models, transaction
from django.utils import timezone

from hypothesis import (
    given,
    settings,
    strategies as st,
)
from hypothesis.extra.django import TestCase as HypothesisDjangoTestCase

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.rbac.user_access_control import (
    ACCESS_CONTROL_RESOURCES,
    RESOURCE_INHERITANCE_MAP,
    AccessControlLevel,
    UserAccessControl,
    access_level_satisfied_for_resource,
    default_access_level,
    get_effective_access_level_for_member,
    get_effective_access_level_for_role,
    highest_access_level,
    minimum_access_level,
    model_to_resource,
    ordered_access_levels,
)
from posthog.scopes import APIScopeObject

try:
    from ee.models.rbac.access_control import AccessControl
    from ee.models.rbac.role import Role, RoleMembership
except ImportError:
    pass

pytestmark = pytest.mark.ee


ALL_RESOURCES = sorted({*ACCESS_CONTROL_RESOURCES, "project", "organization", *RESOURCE_INHERITANCE_MAP})

resources_st = st.sampled_from(ALL_RESOURCES)


@st.composite
def resource_with_levels(draw, n: int = 1):
    resource = draw(resources_st)
    level = st.sampled_from(ordered_access_levels(resource))
    return (resource, *(draw(level) for _ in range(n)))


@st.composite
def member_level_inputs(draw):
    resource = draw(resources_st)
    level = st.sampled_from(ordered_access_levels(resource))
    return (
        resource,
        draw(st.none() | level),  # project default
        draw(st.lists(level, max_size=4)),  # role overrides
        draw(st.none() | level),  # member override
    )


def _max_level(levels: list[AccessControlLevel], order: list[AccessControlLevel]) -> Optional[AccessControlLevel]:
    return max(levels, key=order.index) if levels else None


class TestAccessLevelHelpersProperties(TestCase):
    @given(resource=resources_st)
    @settings(max_examples=500, deadline=None)
    def test_level_helpers_are_consistent(self, resource):
        levels = ordered_access_levels(resource)
        assert levels[0] == "none"
        assert len(set(levels)) == len(levels)
        assert default_access_level(resource) in levels
        assert minimum_access_level(resource) in levels
        assert highest_access_level(resource) in levels
        assert levels.index(minimum_access_level(resource)) <= levels.index(default_access_level(resource))
        assert levels.index(default_access_level(resource)) <= levels.index(highest_access_level(resource))

    @given(data=resource_with_levels(n=3))
    @settings(max_examples=500, deadline=None)
    def test_satisfaction_is_a_total_order(self, data):
        resource, a, b, c = data
        levels = ordered_access_levels(resource)

        assert access_level_satisfied_for_resource(resource, a, b) == (levels.index(a) >= levels.index(b))
        assert access_level_satisfied_for_resource(resource, a, a)
        assert access_level_satisfied_for_resource(resource, a, b) or access_level_satisfied_for_resource(
            resource, b, a
        )
        if access_level_satisfied_for_resource(resource, a, b) and access_level_satisfied_for_resource(resource, b, a):
            assert a == b
        if access_level_satisfied_for_resource(resource, a, b) and access_level_satisfied_for_resource(resource, b, c):
            assert access_level_satisfied_for_resource(resource, a, c)

    @given(data=member_level_inputs())
    @settings(max_examples=500, deadline=None)
    def test_org_admin_member_always_gets_highest(self, data):
        resource, default_level, role_levels, member_level = data
        result = get_effective_access_level_for_member(
            resource, default_level, role_levels, member_level, is_org_admin=True
        )
        assert result.effective_access_level == highest_access_level(resource)
        assert result.inherited_access_level == highest_access_level(resource)
        assert result.inherited_access_level_reason == "organization_admin"

    @given(data=member_level_inputs())
    @settings(max_examples=500, deadline=None)
    def test_effective_member_level_is_max_of_inputs(self, data):
        resource, default_level, role_levels, member_level = data
        result = get_effective_access_level_for_member(
            resource, default_level, role_levels, member_level, is_org_admin=False
        )
        provided = [level for level in [default_level, *role_levels, member_level] if level is not None]
        assert result.effective_access_level == _max_level(provided, ordered_access_levels(resource))

    @given(data=member_level_inputs())
    @settings(max_examples=500, deadline=None)
    def test_effective_member_level_is_monotonic(self, data):
        resource, default_level, role_levels, member_level = data
        levels = ordered_access_levels(resource)
        base = get_effective_access_level_for_member(
            resource, default_level, role_levels, member_level, is_org_admin=False
        )
        for extra in levels:
            extended = get_effective_access_level_for_member(
                resource, default_level, [*role_levels, extra], member_level, is_org_admin=False
            )
            assert extended.effective_access_level is not None
            if base.effective_access_level is not None:
                assert levels.index(extended.effective_access_level) >= levels.index(base.effective_access_level)

    @given(data=resource_with_levels(n=2), has_default=st.booleans(), has_role=st.booleans())
    @settings(max_examples=500, deadline=None)
    def test_effective_role_level_is_max_of_inputs(self, data, has_default, has_role):
        resource, default_level, role_level = data
        default_arg = default_level if has_default else None
        role_arg = role_level if has_role else None
        result = get_effective_access_level_for_role(resource, default_arg, role_arg)

        provided = [level for level in [default_arg, role_arg] if level is not None]
        assert result.effective_access_level == _max_level(provided, ordered_access_levels(resource))
        if default_arg is not None and (role_arg is not None or True):
            assert (result.inherited_access_level_reason == "project_default") == (default_arg is not None)


# ------------------------------------------------------------
# DB-backed model-based tests
#
# The implementation is exercised against a pure oracle across arbitrary
# AccessControl row configurations, membership levels, and resource models.
# Models are discovered from the app registry, so resources added in the
# future are enrolled automatically (the guard test below fails if a new
# model can't be built generically).
# ------------------------------------------------------------

# Resources access controls apply to: the declared resource list plus children
# that inherit from them. project/organization are member-level concepts tested
# via project rows below; plugin is org-scoped with no resource-level controls.
ACCESS_CONTROLLED_RESOURCES = set(ACCESS_CONTROL_RESOURCES) | set(RESOURCE_INHERITANCE_MAP)

# resource -> reason; only for models that genuinely can't be created in a unit test
EXCLUSIONS: dict[str, str] = {}


def discover_object_models() -> list[tuple[str, type[models.Model]]]:
    candidates: dict[str, list[type[models.Model]]] = {}
    for model in apps.get_models():
        resource = model_to_resource(model)  # type: ignore
        if resource and resource in ACCESS_CONTROLLED_RESOURCES and resource not in EXCLUSIONS:
            candidates.setdefault(resource, []).append(model)

    chosen = {}
    for resource, model_classes in candidates.items():
        # Prefer the model named after the resource itself (e.g. Endpoint over EndpointVersion)
        exact = [m for m in model_classes if m._meta.model_name == resource.replace("_", "")]
        chosen[resource] = exact[0] if exact else sorted(model_classes, key=lambda m: m._meta.label)[0]
    return sorted(chosen.items())


OBJECT_MODELS = discover_object_models()

_unique_counter = itertools.count()


def build_instance(model_cls: type[models.Model], team: Team, user: User, _depth: int = 0) -> models.Model:
    if _depth > 3:
        raise ValueError(f"FK chain too deep while building {model_cls.__name__}")

    kwargs: dict = {}
    for field in model_cls._meta.concrete_fields:
        if field.auto_created or field.has_default() or field.null:
            continue
        if field.is_relation:
            if field.related_model is Team:
                kwargs[field.name] = team
            elif field.related_model is User:
                kwargs[field.name] = user
            else:
                kwargs[field.name] = build_instance(
                    cast(type[models.Model], field.related_model), team, user, _depth + 1
                )
        elif isinstance(field, models.JSONField):
            kwargs[field.name] = {}
        elif isinstance(field, models.UUIDField):
            kwargs[field.name] = uuid.uuid4()
        elif isinstance(field, models.DateTimeField):
            kwargs[field.name] = timezone.now()
        elif isinstance(field, models.BooleanField):
            kwargs[field.name] = False
        elif isinstance(field, models.IntegerField | models.FloatField | models.DecimalField):
            kwargs[field.name] = 0
        elif isinstance(field, models.CharField | models.TextField):
            kwargs[field.name] = f"pbt-{field.name}-{next(_unique_counter)}"
        else:
            raise ValueError(f"Cannot generically fill {model_cls.__name__}.{field.name} ({type(field).__name__})")

    if "created_by" not in kwargs and any(f.name == "created_by" for f in model_cls._meta.concrete_fields):
        kwargs["created_by"] = user

    manager = model_cls.objects
    if hasattr(manager, "for_team"):
        # Fail-closed team-scoped managers require an explicit team scope
        manager = manager.for_team(team.id)  # type: ignore
    return manager.create(**kwargs)


def model_has_created_by(model_cls: type[models.Model]) -> bool:
    return any(f.name == "created_by" for f in model_cls._meta.concrete_fields)


# Row targets: who an AccessControl row applies to, relative to self.user
# (who is in role_a; other_user is in role_b).
TARGETS = ("team_default", "self_member", "other_member", "role_a", "role_b")
# Rows _filter_options can ever see for self.user - other_member/role_b rows are invisible
MATCHING = {"team_default", "self_member", "role_a"}

PROJECT_LEVELS = ordered_access_levels("project")
ADMIN_LEVELS = [OrganizationMembership.Level.ADMIN, OrganizationMembership.Level.OWNER]
ALL_MEMBERSHIP_LEVELS = [OrganizationMembership.Level.MEMBER, *ADMIN_LEVELS]


@dataclass(frozen=True)
class RowSpec:
    target: str
    scope: str  # "object" -> resource_id=str(obj.id); "resource" -> resource_id=None on the inheritance parent
    level: AccessControlLevel


def _row_specs(draw, scopes: tuple[str, ...], level: st.SearchStrategy) -> list[RowSpec]:
    # Each (target, scope) combo gets an independent presence draw, which makes
    # configurations with several rows in the same precedence tier common -
    # sparse lists rarely produce the multi-row collisions that distinguish
    # max-wins from other resolution strategies
    combos = [(target, scope) for target in TARGETS for scope in scopes]
    chosen = draw(st.fixed_dictionaries({}, optional=dict.fromkeys(combos, level)))
    return [RowSpec(target=target, scope=scope, level=lvl) for (target, scope), lvl in chosen.items()]


@st.composite
def object_resource_and_rows(draw):
    resource, model_cls = draw(st.sampled_from(OBJECT_MODELS))
    level = st.sampled_from(ordered_access_levels(resource))
    return resource, model_cls, _row_specs(draw, ("object", "resource"), level)


@st.composite
def resource_level_rows(draw):
    resource = draw(st.sampled_from(sorted(ACCESS_CONTROLLED_RESOURCES)))
    effective = RESOURCE_INHERITANCE_MAP.get(resource, resource)
    assert effective is not None
    level = st.sampled_from(ordered_access_levels(effective))
    return resource, _row_specs(draw, ("resource",), level)


@st.composite
def project_rows(draw):
    return _row_specs(draw, ("object",), st.sampled_from(PROJECT_LEVELS))


# Plain members are the only level where row resolution matters, so bias toward them
membership_levels_st = st.one_of(st.just(OrganizationMembership.Level.MEMBER), st.sampled_from(ALL_MEMBERSHIP_LEVELS))


# ------------------------------------------------------------
# Oracle: pure reference implementation of the expected access level
# ------------------------------------------------------------


def oracle_explicit_level(specs: list[RowSpec], order: list[AccessControlLevel]) -> Optional[AccessControlLevel]:
    # Mirrors get_user_access_level(obj, explicit=True): member/role rows on the
    # object win over resource-level rows, which win over object rows including
    # team defaults. Note the shadowing this implies: a self_member "none" row
    # beats a team_default "admin" row even though it is lower.
    matching = [s for s in specs if s.target in MATCHING]
    specific: list[AccessControlLevel] = [
        s.level for s in matching if s.scope == "object" and s.target != "team_default"
    ]
    if specific:
        return _max_level(specific, order)
    resource_rows: list[AccessControlLevel] = [s.level for s in matching if s.scope == "resource"]
    if resource_rows:
        return _max_level(resource_rows, order)
    object_rows: list[AccessControlLevel] = [s.level for s in matching if s.scope == "object"]
    if object_rows:
        return _max_level(object_rows, order)
    return None


def oracle_object_access_level(
    resource: APIScopeObject, specs: list[RowSpec], is_creator: bool, is_org_admin: bool
) -> AccessControlLevel:
    if is_creator or is_org_admin:
        return highest_access_level(resource)
    return oracle_explicit_level(specs, ordered_access_levels(resource)) or default_access_level(resource)


def oracle_resource_access_level(resource: APIScopeObject, specs: list[RowSpec], is_org_admin: bool) -> str:
    effective = RESOURCE_INHERITANCE_MAP.get(resource, resource)
    if is_org_admin:
        return highest_access_level(effective)
    matching: list[AccessControlLevel] = [s.level for s in specs if s.target in MATCHING]
    return _max_level(matching, ordered_access_levels(effective)) or default_access_level(effective)


def oracle_can_modify(
    resource: APIScopeObject,
    object_specs: list[RowSpec],
    project_rows: list[RowSpec],
    is_creator: bool,
    is_org_admin: bool,
) -> bool:
    if is_creator or is_org_admin:
        return True
    if oracle_explicit_level(project_rows, PROJECT_LEVELS) == "admin":
        return True
    explicit = oracle_explicit_level(object_specs, ordered_access_levels(resource))
    return explicit is not None and access_level_satisfied_for_resource(resource, explicit, "manager")


class BaseAccessControlPropertyTest(HypothesisDjangoTestCase, BaseTest):
    # Fixtures live in setUpTestData (class-level atomics): hypothesis runs each
    # example inside Django's per-test transaction via _pre_setup/_post_teardown,
    # so anything created in setUp would not be rolled back between test methods.
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        cls.organization.save()

        cls.other_user = User.objects.create_and_join(cls.organization, "other-pbt@posthog.com", "testtest")
        cls.role_a = Role.objects.create(name="PBT Role A", organization=cls.organization)  # type: ignore
        cls.role_b = Role.objects.create(name="PBT Role B", organization=cls.organization)  # type: ignore
        RoleMembership.objects.create(user=cls.user, role=cls.role_a)  # type: ignore
        RoleMembership.objects.create(user=cls.other_user, role=cls.role_b)  # type: ignore

    def _membership(self, user: User) -> OrganizationMembership:
        return OrganizationMembership.objects.get(user=user, organization=self.organization)

    def _set_membership_level(self, level: OrganizationMembership.Level) -> None:
        membership = self._membership(self.user)
        membership.level = level
        membership.save()

    def _row_kwargs(self, target: str) -> dict:
        if target == "team_default":
            return {}
        if target == "self_member":
            return {"organization_member": self._membership(self.user)}
        if target == "other_member":
            return {"organization_member": self._membership(self.other_user)}
        if target == "role_a":
            return {"role": self.role_a}
        return {"role": self.role_b}

    def _materialize(self, specs: list[RowSpec], resource: APIScopeObject, obj: Optional[models.Model]) -> None:
        parent = RESOURCE_INHERITANCE_MAP.get(resource, resource)
        for spec in specs:
            if spec.scope == "object":
                assert obj is not None
                row_resource, resource_id = resource, str(obj.pk)
            else:
                # Resource-level rows only take effect on the inheritance parent
                row_resource, resource_id = parent, None
            AccessControl.objects.create(  # type: ignore
                team=self.team,
                resource=row_resource,
                resource_id=resource_id,
                access_level=spec.level,
                **self._row_kwargs(spec.target),
            )

    def _materialize_project_rows(self, project_rows: list[RowSpec]) -> None:
        for spec in project_rows:
            AccessControl.objects.create(  # type: ignore
                team=self.team,
                resource="project",
                resource_id=str(self.team.pk),
                access_level=spec.level,
                **self._row_kwargs(spec.target),
            )

    def _fresh_uac(self) -> UserAccessControl:
        return UserAccessControl(self.user, self.team)


class TestUserAccessControlProperties(BaseAccessControlPropertyTest):
    def test_every_access_controlled_model_is_buildable(self):
        failures = []
        for resource, model_cls in OBJECT_MODELS:
            try:
                with transaction.atomic():
                    obj = build_instance(model_cls, self.team, self.user)
                    assert model_to_resource(obj) == resource
            except Exception as e:
                failures.append(f"{resource} ({model_cls.__name__}): {e}")
        assert not failures, (
            "Some access-controlled models cannot be built generically. Either fix build_instance, "
            "or add an EXCLUSIONS entry with a reason:\n" + "\n".join(failures)
        )

    @given(data=object_resource_and_rows(), membership_level=membership_levels_st, own=st.booleans())
    @settings(max_examples=100, deadline=None)
    def test_get_user_access_level_matches_oracle(self, data, membership_level, own):
        resource, model_cls, specs = data
        self._set_membership_level(membership_level)
        creator = self.user if own else self.other_user
        obj = build_instance(model_cls, self.team, creator)
        self._materialize(specs, resource, obj)

        expected = oracle_object_access_level(
            resource,
            specs,
            is_creator=own and model_has_created_by(model_cls),
            is_org_admin=membership_level >= OrganizationMembership.Level.ADMIN,
        )
        assert self._fresh_uac().get_user_access_level(obj) == expected

    @given(data=resource_level_rows(), membership_level=membership_levels_st)
    @settings(max_examples=100, deadline=None)
    def test_access_level_for_resource_matches_oracle(self, data, membership_level):
        resource, specs = data
        self._set_membership_level(membership_level)
        self._materialize(specs, resource, obj=None)

        expected = oracle_resource_access_level(
            resource, specs, is_org_admin=membership_level >= OrganizationMembership.Level.ADMIN
        )
        assert self._fresh_uac().access_level_for_resource(resource) == expected

    @given(
        data=object_resource_and_rows(),
        team_rows=project_rows(),
        membership_level=st.sampled_from(ADMIN_LEVELS),
    )
    @settings(max_examples=50, deadline=None)
    def test_org_admin_always_gets_highest_access(self, data, team_rows, membership_level):
        resource, model_cls, specs = data
        self._set_membership_level(membership_level)
        obj = build_instance(model_cls, self.team, self.other_user)
        self._materialize(specs, resource, obj)
        self._materialize_project_rows(team_rows)

        uac = self._fresh_uac()
        effective = RESOURCE_INHERITANCE_MAP.get(resource, resource)
        assert effective is not None
        assert uac.access_level_for_object(obj) == highest_access_level(resource)
        assert uac.access_level_for_resource(resource) == highest_access_level(effective)
        assert uac.get_user_access_level(obj) == highest_access_level(resource)
        assert uac.check_can_modify_access_levels_for_object(obj) is True

    @given(data=object_resource_and_rows(), admin_target=st.sampled_from(sorted(MATCHING)))
    @settings(max_examples=50, deadline=None)
    def test_project_admin_can_always_modify_access_levels(self, data, admin_target):
        resource, model_cls, specs = data
        obj = build_instance(model_cls, self.team, self.other_user)
        self._materialize(specs, resource, obj)
        # A single matching project-admin row, with no other project rows that
        # could shadow it (a specific "none"/"member" row would win over a
        # team_default "admin" row)
        self._materialize_project_rows([RowSpec(target=admin_target, scope="object", level="admin")])

        assert self._fresh_uac().check_can_modify_access_levels_for_object(obj) is True

    @given(
        data=object_resource_and_rows(),
        team_rows=project_rows(),
        membership_level=membership_levels_st,
        own=st.booleans(),
    )
    @settings(max_examples=100, deadline=None)
    def test_check_can_modify_access_levels_matches_oracle(self, data, team_rows, membership_level, own):
        resource, model_cls, specs = data
        self._set_membership_level(membership_level)
        creator = self.user if own else self.other_user
        obj = build_instance(model_cls, self.team, creator)
        self._materialize(specs, resource, obj)
        self._materialize_project_rows(team_rows)

        expected = oracle_can_modify(
            resource,
            specs,
            team_rows,
            is_creator=own and model_has_created_by(model_cls),
            is_org_admin=membership_level >= OrganizationMembership.Level.ADMIN,
        )
        assert self._fresh_uac().check_can_modify_access_levels_for_object(obj) is expected
