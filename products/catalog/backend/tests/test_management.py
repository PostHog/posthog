from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.models.team import Team

from products.catalog.backend.models import CatalogNode
from products.catalog.backend.system_registry import iter_system_tables


class TestSeedSystemCatalogCommand(BaseTest):
    def test_seed_for_single_team(self) -> None:
        expected = sum(1 for _ in iter_system_tables())
        out = StringIO()
        call_command("seed_system_catalog", team_id=self.team.pk, stdout=out)
        assert CatalogNode.objects.filter(team=self.team, kind=CatalogNode.Kind.SYSTEM_TABLE).count() == expected
        assert f"Seeded {expected} system tables for team {self.team.pk}" in out.getvalue()

    def test_seed_missing_team_id_errors(self) -> None:
        with self.assertRaises(CommandError):
            call_command("seed_system_catalog", team_id=999_999_999, stdout=StringIO())

    def test_seed_all_teams(self) -> None:
        other = Team.objects.create(organization=self.organization, name="Other")
        expected = sum(1 for _ in iter_system_tables())
        out = StringIO()
        call_command("seed_system_catalog", all=True, stdout=out)
        for team in (self.team, other):
            assert CatalogNode.objects.filter(team=team, kind=CatalogNode.Kind.SYSTEM_TABLE).count() == expected, (
                f"team {team.pk} not seeded"
            )

    def test_requires_target(self) -> None:
        with self.assertRaises(CommandError):
            call_command("seed_system_catalog", stdout=StringIO())
