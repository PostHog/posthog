"""Smoke tests for TeamScopedRootMixin wiring.

Manager mechanics (filtering, raise-on-no-context, unscoped, etc.) are
covered exhaustively in test_manager.py against FeatureFlag — those tests
apply unchanged to any TeamScopedManager-backed model. This file just
verifies that inheriting `TeamScopedRootMixin` swaps the manager from
`RootTeamManager` to `TeamScopedManager` while keeping the canonical-team
save() rewrite from the parent — and that the CI introspection (which is
just an isinstance check on `_meta.managers`) recognises all three
adoption styles: the two mixins and an ad-hoc `objects = TeamScopedManager()`.
"""

from types import SimpleNamespace

from django.db import models
from django.test import SimpleTestCase

from parameterized import parameterized

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
    """The CI baseline check (compute_unmigrated_to_fail_closed) scans
    `model._meta.managers` for any `TeamScopedManager` instance. Confirm
    that contract holds for all three adoption styles.

    Scanning the whole managers list (rather than `_default_manager`) keeps
    the detection robust to `Meta.default_manager_name = "all_teams"` —
    set elsewhere so admin / framework managers bypass scoping while user
    code via `Model.objects` stays fail-closed.
    """

    @staticmethod
    def _has_team_scoped_manager(model: type[models.Model]) -> bool:
        return any(isinstance(m, TeamScopedManager) for m in model._meta.managers)

    @parameterized.expand([(ProductTeamModel,), (TeamScopedRootMixin,)])
    def test_mixin_is_detected(self, model_cls: type[models.Model]) -> None:
        self.assertTrue(self._has_team_scoped_manager(model_cls))

    def test_adhoc_declaration_is_detected(self) -> None:
        """A bare `objects = TeamScopedManager()` on a model that doesn't inherit
        either mixin still satisfies the check. We use a SimpleNamespace stub
        rather than a real `models.Model` subclass to avoid registering an
        abstract test model in the live `posthog` app registry."""
        stub = SimpleNamespace(_meta=SimpleNamespace(managers=(TeamScopedManager(),)))
        self.assertTrue(self._has_team_scoped_manager(stub))  # type: ignore[arg-type]
