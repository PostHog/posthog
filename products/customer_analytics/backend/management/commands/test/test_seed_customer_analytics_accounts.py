from io import StringIO

import pytest
from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.models import OrganizationMembership, User
from posthog.persons_db import persons_db_connection
from posthog.persons_seed import insert_seed_group

from products.customer_analytics.backend.models.account import Account
from products.customer_analytics.backend.models.team_customer_analytics_config import TeamCustomerAnalyticsConfig
from products.notebooks.backend.models import Notebook, ResourceNotebook

pytestmark = pytest.mark.persons_db_direct


class TestSeedCustomerAnalyticsAccounts(BaseTest):
    def tearDown(self):
        # _make_group commits rows outside the test transaction, so remove them here to
        # avoid leaking into other tests that share the persons database.
        with persons_db_connection(writer=True) as conn, conn.cursor() as cursor:
            cursor.execute("DELETE FROM posthog_group WHERE team_id = %s", (self.team.pk,))
        super().tearDown()

    def _make_group(self, group_key: str, name: str) -> None:
        # The command reads groups via a raw persons-DB connection, so fixtures must be
        # committed — a Django ORM create would be invisible across the connection boundary.
        with persons_db_connection(writer=True) as conn:
            insert_seed_group(
                conn,
                team_id=self.team.pk,
                group_key=group_key,
                group_type_index=0,
                group_properties={"name": name, "industry": "tech", "team_size": 3},
            )

    def _run(self, **kwargs) -> str:
        out = StringIO()
        call_command("seed_customer_analytics_accounts", team_id=self.team.pk, stdout=out, **kwargs)
        return out.getvalue()

    def _accounts(self) -> dict[str, Account]:
        return {a.external_id: a for a in Account.objects.for_team(self.team.pk) if a.external_id is not None}

    def _pool_emails(self) -> set[str]:
        return set(
            User.objects.filter(email__endswith=f"@team{self.team.pk}.customer-analytics.invalid").values_list(
                "email", flat=True
            )
        )

    def test_seeds_accounts_users_and_notes(self):
        self._make_group("acme-id", "Acme")
        self._make_group("globex-id", "Globex")
        self._make_group("initech-id", "Initech")

        self._run(users=4, accounts_with_notes=2, notes_per_account=2)

        config = TeamCustomerAnalyticsConfig.objects.get(team=self.team)
        assert config.account_group_type_index == 0

        accounts = self._accounts()
        assert set(accounts) == {"acme-id", "globex-id", "initech-id"}
        assert accounts["acme-id"].name == "Acme"

        # Users: a pool joined to the org, assigned as account roles.
        assert len(self._pool_emails()) == 4
        owner = accounts["acme-id"].properties.account_owner
        assert owner is not None
        assert owner.email in self._pool_emails()

        # Notes: only the first two accounts (by group key) get two notes each.
        notebooks = Notebook.objects.filter(resources__account__team_id=self.team.pk)
        assert notebooks.count() == 4
        assert all(notebook.visibility == Notebook.Visibility.INTERNAL for notebook in notebooks)
        accounts_with_notes = set(
            ResourceNotebook.objects.filter(account__team_id=self.team.pk).values_list("account_id", flat=True)
        )
        assert accounts_with_notes == {accounts["acme-id"].id, accounts["globex-id"].id}

    def test_is_idempotent(self):
        self._make_group("acme-id", "Acme")
        self._make_group("globex-id", "Globex")

        self._run(users=3, accounts_with_notes=2, notes_per_account=1)
        self._run(users=3, accounts_with_notes=2, notes_per_account=1)

        assert Account.objects.for_team(self.team.pk).count() == 2
        assert len(self._pool_emails()) == 3
        assert (
            OrganizationMembership.objects.filter(
                organization=self.organization, user__email__endswith=".customer-analytics.invalid"
            ).count()
            == 3
        )
        assert ResourceNotebook.objects.filter(account__team_id=self.team.pk).count() == 2

    def test_dry_run_writes_nothing(self):
        self._make_group("acme-id", "Acme")

        output = self._run(dry_run=True)

        assert "Dry run" in output
        assert Account.objects.for_team(self.team.pk).count() == 0
        assert self._pool_emails() == set()
        assert not TeamCustomerAnalyticsConfig.objects.filter(
            team=self.team, account_group_type_index__isnull=False
        ).exists()

    def test_errors_when_no_groups(self):
        with self.assertRaises(CommandError):
            self._run()
