"""Smoke tests for TeamScopedRootMixin wiring.

Manager mechanics (filtering, raise-on-no-context, unscoped, etc.) are
covered exhaustively in test_manager.py against FeatureFlag — those tests
apply unchanged to any TeamScopedManager-backed model. This file just
verifies that inheriting `TeamScopedRootMixin` swaps the manager from
`RootTeamManager` to `TeamScopedManager` while keeping the canonical-team
save() rewrite from the parent.
"""

from django.test import SimpleTestCase

from posthog.models.scoping.manager import TeamScopedManager
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
