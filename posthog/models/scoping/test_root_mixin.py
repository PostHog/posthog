"""Smoke tests for TeamScopedRootMixin wiring.

Manager mechanics (filtering, raise-on-no-context, unscoped, etc.) are
covered exhaustively in test_manager.py against FeatureFlag — those tests
apply unchanged to any TeamScopedManager-backed model. This file just
verifies that inheriting `TeamScopedRootMixin` swaps the manager from
`RootTeamManager` to `TeamScopedManager` while keeping the canonical-team
save() rewrite from the parent — and that the CI introspection (which is
an isinstance check on the manager named `objects` in `_meta.managers_map`)
recognises all three adoption styles: the two mixins and an ad-hoc
`objects = TeamScopedManager()`.

`TestRootTeamMixinSave` covers when `RootTeamMixin.save()` rewrites a child team to its parent.
"""

from types import SimpleNamespace

from posthog.test.base import BaseTest

from django.db import models
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.scoping.product_mixin import ProductTeamModel
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.team import Team
from posthog.models.user_home_settings import UserHomeSettings
from posthog.models.utils import RootTeamManager, RootTeamMixin


class TestTeamScopedRootMixinWiring(SimpleTestCase):
    def test_objects_is_team_scoped_manager(self) -> None:
        """The default manager is fail-closed by team scope, overriding RootTeamManager."""
        manager = TeamScopedRootMixin._meta.managers_map["objects"]
        self.assertIsInstance(manager, TeamScopedManager)
        self.assertNotIsInstance(manager, RootTeamManager)

    def test_inherits_from_root_team_mixin(self) -> None:
        """Inherits the canonical-team save() rewrite via RootTeamMixin."""
        self.assertTrue(issubclass(TeamScopedRootMixin, RootTeamMixin))

    def test_is_abstract(self) -> None:
        """The mixin itself does not create a table."""
        self.assertTrue(TeamScopedRootMixin._meta.abstract)


class TestFailClosedIntrospection(SimpleTestCase):
    """The CI baseline check (compute_unmigrated_to_fail_closed) verifies
    that the manager accessible as `Model.objects` is a `TeamScopedManager`.
    Confirm that contract holds for all three adoption styles.

    Anchoring on `objects` (rather than scanning all managers) closes the
    loophole reviewers flagged: a model could keep `objects =
    RootTeamManager()` and add a secondary scoped manager just to satisfy
    CI, while call sites like `Model.objects.X` stayed unscoped. Anchoring
    on `objects` also stays correct once #57879 sets
    `Meta.default_manager_name = "all_teams"` on ProductTeamModel —
    `_default_manager` will then resolve to the unscoped sibling for
    Django framework code (admin, related queries), but `Model.objects`
    will still resolve to the TeamScopedManager declared on the model.
    """

    @staticmethod
    def _objects_is_team_scoped(model: type[models.Model]) -> bool:
        return isinstance(model._meta.managers_map.get("objects"), TeamScopedManager)

    def test_product_team_model_is_detected(self) -> None:
        self.assertTrue(self._objects_is_team_scoped(ProductTeamModel))

    def test_team_scoped_root_mixin_is_detected(self) -> None:
        self.assertTrue(self._objects_is_team_scoped(TeamScopedRootMixin))

    def test_adhoc_declaration_is_detected(self) -> None:
        """A bare `objects = TeamScopedManager()` on a model that doesn't inherit
        either mixin still satisfies the check. We use a SimpleNamespace stub
        rather than a real `models.Model` subclass to avoid registering an
        abstract test model in the live `posthog` app registry."""
        stub = SimpleNamespace(_meta=SimpleNamespace(managers_map={"objects": TeamScopedManager()}))
        self.assertTrue(self._objects_is_team_scoped(stub))  # type: ignore[arg-type]

    def test_bypass_via_secondary_manager_is_not_detected(self) -> None:
        """A model with `objects = RootTeamManager()` and a secondary
        TeamScopedManager should NOT count as migrated — call sites
        still use Model.objects, which is unscoped."""
        stub = SimpleNamespace(
            _meta=SimpleNamespace(
                managers_map={
                    "objects": RootTeamManager(),
                    "scoped": TeamScopedManager(),
                }
            )
        )
        self.assertFalse(self._objects_is_team_scoped(stub))  # type: ignore[arg-type]


class TestRootTeamMixinSave(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Environment")

    def test_insert_on_a_child_team_stores_the_parent(self) -> None:
        home = UserHomeSettings.objects.create(team=self.child, user=self.user)

        assert home.team_id == self.team.id

    @parameterized.expand(
        [
            ("full_save", None),
            ("team_in_update_fields", ["team"]),
            ("team_id_in_update_fields", ["team_id"]),
        ]
    )
    def test_save_that_writes_the_team_stores_the_parent(self, _name: str, update_fields: list[str] | None) -> None:
        home = UserHomeSettings.objects.create(team=self.team, user=self.user)
        home.team = self.child

        home.save(update_fields=update_fields)

        assert UserHomeSettings.objects.get(pk=home.pk).team_id == self.team.id

    @parameterized.expand([("list", lambda: ["tabs"]), ("iterator", lambda: iter(["tabs"]))])
    def test_partial_update_without_the_team_does_not_load_it(self, _name: str, update_fields) -> None:
        created = UserHomeSettings.objects.create(team=self.team, user=self.user)
        home = UserHomeSettings.objects.get(pk=created.pk)
        home.tabs = [{"id": "home"}]

        home.save(update_fields=update_fields())

        assert not UserHomeSettings.team.is_cached(home)
        assert UserHomeSettings.objects.get(pk=home.pk).tabs == [{"id": "home"}]
