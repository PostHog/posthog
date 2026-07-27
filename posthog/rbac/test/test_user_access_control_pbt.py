import uuid
import itertools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional, cast

import pytest
from posthog.test.base import BaseTest
from unittest import TestCase

from django.apps import apps
from django.db import models, transaction
from django.utils import timezone

from hypothesis import (
    HealthCheck,
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
    NO_ACCESS_LEVEL,
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

# PostHog CI runs the backend suite with pytest-rerunfailures (--reruns 2). A rerun
# re-instantiates the TestCase, so a genuinely-failing @given method is re-invoked
# from a fresh instance, which trips hypothesis's differing_executors health check
# and masks the real falsifying example. Each example already runs in its own
# transaction (the Django hypothesis TestCase), so cross-instance reruns are benign
# here - suppress the check so a real regression surfaces its falsifying example.
SUPPRESSED_HEALTH_CHECKS = [HealthCheck.differing_executors]


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
    if not levels:
        return None
    # Separate statement so mypy infers max()'s type var from the arguments
    # rather than widening it to the Optional return type
    best = max(levels, key=order.index)
    return best


class TestAccessLevelHelpersProperties(TestCase):
    @given(resource=resources_st)
    @settings(max_examples=500, deadline=None, suppress_health_check=SUPPRESSED_HEALTH_CHECKS)
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
    @settings(max_examples=500, deadline=None, suppress_health_check=SUPPRESSED_HEALTH_CHECKS)
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
    @settings(max_examples=500, deadline=None, suppress_health_check=SUPPRESSED_HEALTH_CHECKS)
    def test_org_admin_member_always_gets_highest(self, data):
        resource, default_level, role_levels, member_level = data
        result = get_effective_access_level_for_member(
            resource, default_level, role_levels, member_level, is_org_admin=True
        )
        assert result.effective_access_level == highest_access_level(resource)
        assert result.inherited_access_level == highest_access_level(resource)
        assert result.inherited_access_level_reason == "organization_admin"

    @given(data=member_level_inputs())
    @settings(max_examples=500, deadline=None, suppress_health_check=SUPPRESSED_HEALTH_CHECKS)
    def test_effective_member_level_is_max_of_inputs(self, data):
        resource, default_level, role_levels, member_level = data
        result = get_effective_access_level_for_member(
            resource, default_level, role_levels, member_level, is_org_admin=False
        )
        provided = [level for level in [default_level, *role_levels, member_level] if level is not None]
        assert result.effective_access_level == _max_level(provided, ordered_access_levels(resource))

    @given(data=member_level_inputs())
    @settings(max_examples=500, deadline=None, suppress_health_check=SUPPRESSED_HEALTH_CHECKS)
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
    @settings(max_examples=500, deadline=None, suppress_health_check=SUPPRESSED_HEALTH_CHECKS)
    def test_effective_role_level_is_max_of_inputs(self, data, has_default, has_role):
        resource, default_level, role_level = data
        default_arg = default_level if has_default else None
        role_arg = role_level if has_role else None
        result = get_effective_access_level_for_role(resource, default_arg, role_arg)

        provided = [level for level in [default_arg, role_arg] if level is not None]
        assert result.effective_access_level == _max_level(provided, ordered_access_levels(resource))
        # The inherited reason is "project_default" exactly when a default level is present,
        # regardless of whether a role override is also present.
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


def _build_evaluation(team: Team, user: User, model_cls: type[models.Model]) -> models.Model:
    # Evaluation.save() enforces an interdependent (evaluation_type, output_type)
    # combo plus per-combo config validation that the generic field-filler can't
    # satisfy. sentiment/sentiment is the combo that needs no model configuration
    # and accepts empty configs. If the valid combos change, the buildable guard
    # test fails loudly and this factory should be updated.
    manager: Any = model_cls._default_manager
    return manager.create(
        team=team,
        name="pbt-evaluation",
        evaluation_type="sentiment",
        output_type="sentiment",
        evaluation_config={},
        output_config={},
        created_by=user,
    )


# resource -> factory for models whose validation the generic build_instance can't
# satisfy. Preferred over EXCLUSIONS so the resource keeps coverage.
FACTORY_OVERRIDES: dict[APIScopeObject, Callable[[Team, User, type[models.Model]], models.Model]] = {
    "evaluation": _build_evaluation,
}


def discover_object_models() -> list[tuple[APIScopeObject, type[models.Model]]]:
    candidates: dict[APIScopeObject, list[type[models.Model]]] = {}
    for model in apps.get_models():
        # model_to_resource only touches _meta, which exists on the class too
        resource = model_to_resource(cast(models.Model, model))
        if resource and resource in ACCESS_CONTROLLED_RESOURCES and resource not in EXCLUSIONS:
            candidates.setdefault(resource, []).append(model)

    chosen: dict[APIScopeObject, type[models.Model]] = {}
    for candidate_resource, model_classes in candidates.items():
        # Prefer the model named after the resource itself (e.g. Endpoint over EndpointVersion)
        exact = [m for m in model_classes if m._meta.model_name == candidate_resource.replace("_", "")]
        chosen[candidate_resource] = exact[0] if exact else sorted(model_classes, key=lambda m: m._meta.label)[0]
    return sorted(chosen.items())


OBJECT_MODELS = discover_object_models()

_unique_counter = itertools.count()


def build_instance(model_cls: type[models.Model], team: Team, user: User, _depth: int = 0) -> models.Model:
    if _depth > 3:
        raise ValueError(f"FK chain too deep while building {model_cls.__name__}")

    override_resource = model_to_resource(cast(models.Model, model_cls))
    if override_resource in FACTORY_OVERRIDES:
        return FACTORY_OVERRIDES[override_resource](team, user, model_cls)

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

    manager: Any = model_cls._default_manager
    if hasattr(manager, "for_team"):
        # Fail-closed team-scoped managers require an explicit team scope
        manager = manager.for_team(team.id)
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


@st.composite
def queryset_scenario(draw):
    # Several objects of one resource, each with its own object-level rows, plus a
    # set of resource-level rows. Drives the queryset/object-id resolution path
    # (filter_queryset_by_access_level / blocked_resource_ids_by_scope) where the
    # interaction across multiple objects and resource-level access matters.
    resource, model_cls = draw(st.sampled_from(OBJECT_MODELS))
    effective = RESOURCE_INHERITANCE_MAP.get(resource, resource)
    object_level = st.sampled_from(ordered_access_levels(resource))
    resource_level = st.sampled_from(ordered_access_levels(effective))

    n_objects = draw(st.integers(min_value=1, max_value=3))
    objects = [(_row_specs(draw, ("object",), object_level), draw(st.booleans())) for _ in range(n_objects)]
    resource_specs = _row_specs(draw, ("resource",), resource_level)
    return resource, model_cls, objects, resource_specs


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


def oracle_blocked_and_allowed_object_ids(
    object_specs_by_id: dict[str, list[RowSpec]],
) -> tuple[set[str], set[str]]:
    # Mirrors _blocked_and_allowed_object_ids over the rows visible to self.user
    # (only MATCHING targets survive _filter_options). Explicit (role/member) rows
    # decide an object: any non-"none" explicit row allows it, otherwise it's blocked.
    # With no explicit row, the object is blocked only when every default row is "none".
    blocked: set[str] = set()
    allowed: set[str] = set()
    for resource_id, specs in object_specs_by_id.items():
        matching = [s for s in specs if s.target in MATCHING]
        if not matching:
            continue
        explicit = [s for s in matching if s.target != "team_default"]
        if not explicit:
            if all(s.level == NO_ACCESS_LEVEL for s in matching):
                blocked.add(resource_id)
            continue
        if any(s.level != NO_ACCESS_LEVEL for s in explicit):
            allowed.add(resource_id)
        else:
            blocked.add(resource_id)
    return blocked, allowed


def oracle_visible_object_ids(
    resource: APIScopeObject,
    resource_specs: list[RowSpec],
    object_specs_by_id: dict[str, list[RowSpec]],
    creator_ids: set[str],
    model_has_creator: bool,
    is_org_admin: bool,
) -> set[str]:
    # Mirrors filter_queryset_by_access_level (include_all_if_admin=False).
    all_ids = set(object_specs_by_id)
    blocked, allowed = oracle_blocked_and_allowed_object_ids(object_specs_by_id)
    has_resource_access = oracle_resource_access_level(resource, resource_specs, is_org_admin) != NO_ACCESS_LEVEL
    creators = creator_ids if model_has_creator else set()

    if not has_resource_access and allowed:
        return (allowed | creators) & all_ids
    if blocked:
        return all_ids - (blocked - creators)
    return all_ids


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
    other_user: User
    role_a: "Role"
    role_b: "Role"

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
        cls.role_a = Role.objects.create(name="PBT Role A", organization=cls.organization)
        cls.role_b = Role.objects.create(name="PBT Role B", organization=cls.organization)
        RoleMembership.objects.create(user=cls.user, role=cls.role_a)
        RoleMembership.objects.create(user=cls.other_user, role=cls.role_b)

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
            AccessControl.objects.create(
                team=self.team,
                resource=row_resource,
                resource_id=resource_id,
                access_level=spec.level,
                **self._row_kwargs(spec.target),
            )

    def _materialize_project_rows(self, project_rows: list[RowSpec]) -> None:
        for spec in project_rows:
            AccessControl.objects.create(
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
            "add a FACTORY_OVERRIDES factory for the resource, or add an EXCLUSIONS entry with a reason:\n"
            + "\n".join(failures)
        )

    @given(data=object_resource_and_rows(), membership_level=membership_levels_st, own=st.booleans())
    @settings(max_examples=100, deadline=None, suppress_health_check=SUPPRESSED_HEALTH_CHECKS)
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
    @settings(max_examples=100, deadline=None, suppress_health_check=SUPPRESSED_HEALTH_CHECKS)
    def test_access_level_for_resource_matches_oracle(self, data, membership_level):
        resource, specs = data
        self._set_membership_level(membership_level)
        self._materialize(specs, resource, obj=None)

        expected = oracle_resource_access_level(
            resource, specs, is_org_admin=membership_level >= OrganizationMembership.Level.ADMIN
        )
        assert self._fresh_uac().access_level_for_resource(resource) == expected

    @given(data=resource_level_rows(), membership_level=membership_levels_st)
    @settings(max_examples=100, deadline=None, suppress_health_check=SUPPRESSED_HEALTH_CHECKS)
    def test_has_resource_access_and_blocked_resources_match_oracle(self, data, membership_level):
        resource, specs = data
        self._set_membership_level(membership_level)
        self._materialize(specs, resource, obj=None)
        is_org_admin = membership_level >= OrganizationMembership.Level.ADMIN

        uac = self._fresh_uac()
        level = oracle_resource_access_level(resource, specs, is_org_admin=is_org_admin)
        assert uac.has_resource_access(resource) == (level != NO_ACCESS_LEVEL)

        # blocked_resources lists resources with resource-level rows the user can't access;
        # rows land on the inheritance parent, and only rows matching the user are visible.
        effective = RESOURCE_INHERITANCE_MAP.get(resource, resource)
        if is_org_admin or not any(s.target in MATCHING for s in specs):
            expected_blocked: list[str] = []
        else:
            expected_blocked = [effective] if level == NO_ACCESS_LEVEL else []
        assert uac.blocked_resources == expected_blocked

    @given(scenario=queryset_scenario(), membership_level=membership_levels_st)
    @settings(max_examples=50, deadline=None, suppress_health_check=SUPPRESSED_HEALTH_CHECKS)
    def test_filter_queryset_by_access_level_matches_oracle(self, scenario, membership_level):
        resource, model_cls, objects, resource_specs = scenario
        self._set_membership_level(membership_level)

        object_specs_by_id: dict[str, list[RowSpec]] = {}
        creator_ids: set[str] = set()
        built_pks: list = []
        for specs, owned in objects:
            creator = self.user if owned else self.other_user
            obj = build_instance(model_cls, self.team, creator)
            self._materialize(specs, resource, obj)
            object_specs_by_id[str(obj.pk)] = specs
            built_pks.append(obj.pk)
            if owned:
                creator_ids.add(str(obj.pk))
        self._materialize(resource_specs, resource, obj=None)

        manager: Any = model_cls._default_manager
        base = manager.for_team(self.team.id) if hasattr(manager, "for_team") else manager
        queryset = base.filter(pk__in=built_pks)

        filtered = self._fresh_uac().filter_queryset_by_access_level(queryset)
        result_ids = {str(pk) for pk in filtered.values_list("pk", flat=True)}

        expected = oracle_visible_object_ids(
            resource,
            resource_specs,
            object_specs_by_id,
            creator_ids,
            model_has_creator=model_has_created_by(model_cls),
            is_org_admin=membership_level >= OrganizationMembership.Level.ADMIN,
        )
        assert result_ids == expected

    @given(scenario=queryset_scenario(), membership_level=membership_levels_st)
    @settings(max_examples=50, deadline=None, suppress_health_check=SUPPRESSED_HEALTH_CHECKS)
    def test_blocked_resource_ids_by_scope_matches_oracle(self, scenario, membership_level):
        resource, model_cls, objects, resource_specs = scenario
        self._set_membership_level(membership_level)

        object_specs_by_id: dict[str, list[RowSpec]] = {}
        for specs, owned in objects:
            creator = self.user if owned else self.other_user
            obj = build_instance(model_cls, self.team, creator)
            self._materialize(specs, resource, obj)
            object_specs_by_id[str(obj.pk)] = specs
        # Resource-level rows must not leak into the object-scope result
        self._materialize(resource_specs, resource, obj=None)

        result = self._fresh_uac().blocked_resource_ids_by_scope

        if membership_level >= OrganizationMembership.Level.ADMIN:
            assert result == {}
            return
        blocked, _allowed = oracle_blocked_and_allowed_object_ids(object_specs_by_id)
        assert result == ({resource: blocked} if blocked else {})

    @given(
        data=object_resource_and_rows(),
        team_rows=project_rows(),
        membership_level=st.sampled_from(ADMIN_LEVELS),
    )
    @settings(max_examples=50, deadline=None, suppress_health_check=SUPPRESSED_HEALTH_CHECKS)
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
    @settings(max_examples=50, deadline=None, suppress_health_check=SUPPRESSED_HEALTH_CHECKS)
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
    @settings(max_examples=100, deadline=None, suppress_health_check=SUPPRESSED_HEALTH_CHECKS)
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
