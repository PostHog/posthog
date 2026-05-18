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
"""

from types import SimpleNamespace

from django.db import models
from django.test import SimpleTestCase

from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.scoping.product_mixin import ProductTeamModel
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
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
