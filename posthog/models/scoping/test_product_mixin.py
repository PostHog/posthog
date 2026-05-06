import pytest

from django.test import SimpleTestCase

from posthog.models.scoping import team_scope, unscoped
from posthog.models.scoping.manager import TeamScopeError
from posthog.models.scoping.product_mixin import ProductTeamManager, ProductTeamQuerySet


class TestProductTeamQuerySet(SimpleTestCase):
    def test_unscoped_returns_fresh_queryset(self) -> None:
        from products.visual_review.backend.models import Repo

        qs: ProductTeamQuerySet = ProductTeamQuerySet(model=Repo)
        unscoped_qs = qs.unscoped()
        self.assertIsInstance(unscoped_qs, ProductTeamQuerySet)
        self.assertIsNot(qs, unscoped_qs)


class TestProductTeamManagerScoping(SimpleTestCase):
    def _make_manager(self) -> ProductTeamManager:
        from products.visual_review.backend.models import Repo

        mgr: ProductTeamManager = ProductTeamManager()
        mgr.model = Repo
        mgr.auto_created = True
        return mgr

    def test_no_context_raises_team_scope_error(self) -> None:
        with pytest.raises(TeamScopeError, match="No team context set"):
            self._make_manager().get_queryset()

    def test_with_context_filters_by_team(self) -> None:
        # Manager filters directly by ctx.team_id — no DB lookup required,
        # so synthetic team ids work fine in this SimpleTestCase.
        with team_scope(42, canonical=True):
            qs = self._make_manager().get_queryset()
            self.assertTrue(qs.query.has_filters())

    def test_unscoped_context_manager_raises_without_scope(self) -> None:
        with team_scope(42, canonical=True):
            with unscoped():
                with pytest.raises(TeamScopeError):
                    self._make_manager().get_queryset()

    def test_for_team_explicit_scoping(self) -> None:
        # canonical=True so the synthetic id doesn't trigger a Team lookup
        qs = self._make_manager().for_team(99, canonical=True)
        self.assertTrue(qs.query.has_filters())

    def test_unscoped_manager_returns_unfiltered(self) -> None:
        with team_scope(42, canonical=True):
            qs = self._make_manager().unscoped()
            self.assertFalse(qs.query.has_filters())

    def test_unscoped_manager_works_without_context(self) -> None:
        qs = self._make_manager().unscoped()
        self.assertFalse(qs.query.has_filters())
