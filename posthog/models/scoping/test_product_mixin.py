"""Smoke tests for ProductTeamModel wiring.

Manager mechanics (filtering, raise-on-no-context, unscoped, etc.) are
covered exhaustively in test_manager.py against FeatureFlag. After the
ProductTeamManager → TeamScopedManager consolidation those tests apply
unchanged to ProductTeamModel-based models.

Concrete-model integration tests live inside the consuming product
(e.g. visual_review/backend/tests/) where they can import the model
internally without crossing tach product-isolation boundaries.

This file just verifies the abstract base itself is wired up correctly.
"""

from django.db import models
from django.test import SimpleTestCase

from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.scoping.product_mixin import ProductTeamModel


class TestProductTeamModelWiring(SimpleTestCase):
    def test_objects_is_team_scoped_manager(self) -> None:
        """The default manager is fail-closed by team scope."""
        self.assertIsInstance(ProductTeamModel._meta.managers_map["objects"], TeamScopedManager)

    def test_all_teams_is_plain_manager(self) -> None:
        """The bypass manager is a plain Django Manager (no scope enforcement)."""
        all_teams_manager = ProductTeamModel._meta.managers_map["all_teams"]
        self.assertIsInstance(all_teams_manager, models.Manager)
        self.assertNotIsInstance(all_teams_manager, TeamScopedManager)

    def test_team_id_field_is_bigint(self) -> None:
        """team_id is a plain BigIntegerField (no FK across DBs)."""
        field = ProductTeamModel._meta.get_field("team_id")
        self.assertIsInstance(field, models.BigIntegerField)
