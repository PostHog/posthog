from posthog.test.base import BaseTest

from django.test import TestCase

from posthog.models.organization import Organization
from posthog.models.team import Team

from products.catalog.backend.models import CatalogNode
from products.catalog.backend.system_registry import iter_system_tables


class TestSeedSystemTablesOnTeamCreate(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.organization = Organization.objects.create(name="Test Org")

    def test_creating_team_seeds_system_tables(self) -> None:
        expected = sum(1 for _ in iter_system_tables())
        with self.captureOnCommitCallbacks(execute=True):
            team = Team.objects.create(organization=self.organization, name="Seeded")
        count = CatalogNode.objects.filter(team=team, kind=CatalogNode.Kind.SYSTEM_TABLE).count()
        assert count == expected

    def test_saving_existing_team_does_not_reseed(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            team = Team.objects.create(organization=self.organization, name="Once")
        first_count = CatalogNode.objects.filter(team=team, kind=CatalogNode.Kind.SYSTEM_TABLE).count()

        with self.captureOnCommitCallbacks(execute=True):
            team.name = "Renamed"
            team.save()

        # No duplicates created on a non-creation save.
        assert CatalogNode.objects.filter(team=team, kind=CatalogNode.Kind.SYSTEM_TABLE).count() == first_count


class TestSeedNoOpWhenCommitFails(BaseTest):
    """`BaseTest` wraps each test in a transaction that never commits, so the
    on_commit callback should not fire and no system_table rows should be
    seeded by the signal — only by explicit calls."""

    def test_no_seeding_when_on_commit_does_not_fire(self) -> None:
        before = CatalogNode.objects.filter(team=self.team, kind=CatalogNode.Kind.SYSTEM_TABLE).count()
        Team.objects.create(organization=self.organization, name="Not seeded")
        after = CatalogNode.objects.filter(kind=CatalogNode.Kind.SYSTEM_TABLE).count()
        assert after == before
