from io import StringIO

import pytest
from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.models import OrganizationMembership, User
from posthog.persons_db import persons_db_connection
from posthog.persons_seed import insert_seed_group

from products.conversations.backend.models import (
    EmailThread,
    EmailThreadAccountLink,
    EmailThreadMessage,
    EmailThreadParticipant,
)
from products.conversations.backend.models.ticket import Ticket
from products.customer_analytics.backend.management.seed_widget_data import BILLING_INSIGHT_SHORT_IDS
from products.customer_analytics.backend.models import AccountChannelSummary, Meeting, MeetingParticipant
from products.customer_analytics.backend.models.account import Account, AccountProperties
from products.customer_analytics.backend.models.account_channel_summary import SlackSummaryCadence
from products.customer_analytics.backend.models.relationship import AccountRelationship
from products.customer_analytics.backend.models.team_customer_analytics_config import TeamCustomerAnalyticsConfig
from products.notebooks.backend.facade.content import is_markdown_notebook_content
from products.notebooks.backend.models import Notebook, ResourceNotebook
from products.product_analytics.backend.facade.models import Insight, InsightVariable

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

        # Users: a pool joined to the org, assigned as account relationships.
        assert len(self._pool_emails()) == 4
        holders = AccountRelationship.objects.for_team(self.team.pk).filter(
            account=accounts["acme-id"], ended_at__isnull=True
        )
        assert {rel.definition.name for rel in holders} == {"CSM", "Account executive", "Account owner"}
        assert all(rel.user is not None and rel.user.email in self._pool_emails() for rel in holders)

        # Notes: only the first two accounts (by group key) get two notes each.
        notebooks = Notebook.objects.filter(resources__account__team_id=self.team.pk)
        assert notebooks.count() == 4
        assert all(notebook.visibility == Notebook.Visibility.INTERNAL for notebook in notebooks)
        assert all(is_markdown_notebook_content(notebook.content) for notebook in notebooks)
        accounts_with_notes = set(
            ResourceNotebook.objects.filter(account__team_id=self.team.pk).values_list("account_id", flat=True)
        )
        assert accounts_with_notes == {accounts["acme-id"].id, accounts["globex-id"].id}

        assert set(Insight.objects.filter(team=self.team).values_list("short_id", flat=True)) >= set(
            BILLING_INSIGHT_SHORT_IDS.values()
        )
        assert set(InsightVariable.objects.filter(team=self.team).values_list("code_name", flat=True)) >= {
            "billing_org_id",
            "billing_start_date",
            "billing_end_date",
        }

        assert Meeting.objects.for_team(self.team.pk).count() == 6
        assert MeetingParticipant.objects.for_team(self.team.pk).count() == 18
        assert EmailThread.objects.for_team(self.team.pk).count() == 3
        assert EmailThreadAccountLink.objects.for_team(self.team.pk).count() == 3
        assert EmailThreadMessage.objects.for_team(self.team.pk).count() == 6
        assert EmailThreadParticipant.objects.for_team(self.team.pk).count() == 6
        assert Ticket.objects.filter(team=self.team).count() == 3
        assert AccountChannelSummary.objects.for_team(self.team.pk).count() == 3
        assert all(account.properties.email_domains for account in accounts.values())
        assert all(account.properties.slack_channel_id for account in accounts.values())

    def test_is_idempotent(self):
        self._make_group("acme-id", "Acme")
        self._make_group("globex-id", "Globex")

        self._run(users=3, accounts_with_notes=2, notes_per_account=1)

        account = self._accounts()["acme-id"]
        account.properties = AccountProperties(
            website_domain="acme.example.com",
            email_domains=["acme.example.com"],
            known_emails=["contact@acme.example.com"],
            slack_channel_id="CUSER0001",
        )
        account.slack_summary_cadence = SlackSummaryCadence.MONTHLY
        account.save(update_fields=["_properties", "slack_summary_cadence", "updated_at"])
        insight = Insight.objects.get(team=self.team, short_id=BILLING_INSIGHT_SHORT_IDS["usage"])
        insight.name = "Custom billing usage"
        insight.query = {"kind": "TrendsQuery", "series": []}
        insight.save()

        self._run(users=3, accounts_with_notes=2, notes_per_account=1)

        account.refresh_from_db()
        insight.refresh_from_db()
        assert account.properties.website_domain == "acme.example.com"
        assert account.properties.email_domains == ["acme.example.com"]
        assert account.properties.known_emails == ["contact@acme.example.com"]
        assert account.properties.slack_channel_id == "CUSER0001"
        assert account.slack_summary_cadence == SlackSummaryCadence.MONTHLY
        assert insight.name == "Custom billing usage"
        assert insight.query == {"kind": "TrendsQuery", "series": []}

        assert Account.objects.for_team(self.team.pk).count() == 2
        assert len(self._pool_emails()) == 3
        assert (
            OrganizationMembership.objects.filter(
                organization=self.organization, user__email__endswith=".customer-analytics.invalid"
            ).count()
            == 3
        )
        assert ResourceNotebook.objects.filter(account__team_id=self.team.pk).count() == 2
        assert Insight.objects.filter(team=self.team, short_id__in=BILLING_INSIGHT_SHORT_IDS.values()).count() == 3
        assert Meeting.objects.for_team(self.team.pk).count() == 4
        assert MeetingParticipant.objects.for_team(self.team.pk).count() == 12
        assert EmailThread.objects.for_team(self.team.pk).count() == 2
        assert EmailThreadAccountLink.objects.for_team(self.team.pk).count() == 2
        assert EmailThreadMessage.objects.for_team(self.team.pk).count() == 4
        assert EmailThreadParticipant.objects.for_team(self.team.pk).count() == 4
        assert Ticket.objects.filter(team=self.team).count() == 2
        assert AccountChannelSummary.objects.for_team(self.team.pk).count() == 2

    def test_preserves_colliding_soft_deleted_insight(self):
        self._make_group("acme-id", "Acme")
        short_id = BILLING_INSIGHT_SHORT_IDS["usage"]
        insight = Insight.objects_including_soft_deleted.create(
            team=self.team,
            short_id=short_id,
            name="Deleted billing usage",
            query={"kind": "TrendsQuery", "series": []},
            deleted=True,
        )

        self._run(accounts_with_widget_data=0)

        insight.refresh_from_db()
        assert insight.deleted
        assert insight.name == "Deleted billing usage"
        assert insight.query == {"kind": "TrendsQuery", "series": []}
        assert Insight.objects_including_soft_deleted.filter(team=self.team, short_id=short_id).count() == 1

    def test_rejects_negative_widget_account_count_before_dry_run(self):
        with self.assertRaisesMessage(CommandError, "--accounts-with-widget-data must be zero or greater."):
            self._run(dry_run=True, accounts_with_widget_data=-1)

    def test_dry_run_writes_nothing(self):
        self._make_group("acme-id", "Acme")

        output = self._run(dry_run=True)

        assert "Dry run" in output
        assert Account.objects.for_team(self.team.pk).count() == 0
        assert self._pool_emails() == set()
        assert not TeamCustomerAnalyticsConfig.objects.filter(
            team=self.team, account_group_type_index__isnull=False
        ).exists()
        assert not Insight.objects.filter(team=self.team, short_id__in=BILLING_INSIGHT_SHORT_IDS.values()).exists()
        assert not Meeting.objects.for_team(self.team.pk).exists()
        assert not EmailThread.objects.for_team(self.team.pk).exists()
        assert not Ticket.objects.filter(team=self.team).exists()

    def test_errors_when_no_groups(self):
        with self.assertRaises(CommandError):
            self._run()
