"""Smoke tests for TeamScopedRootMixin wiring.

Manager mechanics (filtering, raise-on-no-context, unscoped, etc.) are
covered exhaustively in test_manager.py against FeatureFlag — those tests
apply unchanged to any TeamScopedManager-backed model. This file just
verifies that inheriting `TeamScopedRootMixin` swaps the manager from
`RootTeamManager` to `TeamScopedManager` while keeping the canonical-team
save() rewrite from the parent — and that the CI introspection (which is
just an isinstance check on `_meta.default_manager`) recognises all three
adoption styles: the two mixins and an ad-hoc `objects = TeamScopedManager()`.
"""

from django.db import models
from django.test import SimpleTestCase

from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.scoping.product_mixin import ProductTeamModel
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import RootTeamManager, RootTeamMixin


class _AdHocFailClosed(models.Model):
    """Abstract model that declares `objects = TeamScopedManager()` directly,
    bypassing both mixins. Mirrors the pattern existing main-DB models use
    when migrating off `RootTeamManager` without switching to the new mixin
    (e.g. they need a custom manager subclass that inherits TeamScopedManager).
    """

    objects = TeamScopedManager()

    class Meta:
        abstract = True
        app_label = "posthog"


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
    """The CI baseline check (compute_unmigrated_to_fail_closed) reads
    `model._meta.default_manager` and tests `isinstance(_, TeamScopedManager)`.
    Confirm that contract holds for all three adoption styles.
    """

    def test_product_team_model_is_detected(self) -> None:
        self.assertIsInstance(ProductTeamModel._meta.default_manager, TeamScopedManager)

    def test_team_scoped_root_mixin_is_detected(self) -> None:
        self.assertIsInstance(TeamScopedRootMixin._meta.default_manager, TeamScopedManager)

    def test_adhoc_declaration_is_detected(self) -> None:
        """A bare `objects = TeamScopedManager()` on a plain model also satisfies
        the check — no mixin required, useful when a model already inherits a
        custom base or needs a TeamScopedManager subclass."""
        self.assertIsInstance(_AdHocFailClosed._meta.default_manager, TeamScopedManager)
