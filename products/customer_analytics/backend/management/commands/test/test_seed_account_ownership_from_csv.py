import os
import csv
import tempfile
from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.models import OrganizationMembership, User

from products.customer_analytics.backend.models.account import Account, AccountAssignment, AccountProperties
from products.customer_analytics.backend.test.factories import create_account

CSV_COLUMNS = ["org_id", "account_name", "ae_email", "ae_name", "csm_email", "csm_name"]


class TestSeedAccountOwnershipFromCsv(BaseTest):
    def setUp(self):
        super().setUp()
        self.ae = User.objects.create_and_join(
            organization=self.organization,
            email="anna@x.com",
            password=None,
            first_name="Anna",
            level=OrganizationMembership.Level.MEMBER,
        )
        self.csm = User.objects.create_and_join(
            organization=self.organization,
            email="carl@x.com",
            password=None,
            first_name="Carl",
            level=OrganizationMembership.Level.MEMBER,
        )

    def _write_csv(self, rows) -> str:
        f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="")
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def _run(self, csv_path: str, **kwargs) -> str:
        out = StringIO()
        call_command(
            "seed_account_ownership_from_csv", team_id=self.team.pk, csv=csv_path, stdout=out, stderr=out, **kwargs
        )
        return out.getvalue()

    def _account(self, external_id: str) -> Account:
        return Account.objects.unscoped().get(team_id=self.team.pk, external_id=external_id)

    def test_assigns_roles_and_creates_missing_accounts(self):
        create_account(team_id=self.team.id, name="Existing", external_id="org-1")
        csv_path = self._write_csv(
            [
                # Case-variant email must still resolve to the org member.
                {"org_id": "org-1", "account_name": "Existing", "ae_email": "Anna@X.com", "ae_name": "Anna"},
                {"org_id": "org-new", "account_name": "Brand New", "csm_email": "carl@x.com", "csm_name": "Carl"},
            ]
        )

        output = self._run(csv_path, create_missing=True)

        existing = self._account("org-1")
        assert existing.properties.account_executive is not None
        self.assertEqual(existing.properties.account_executive.id, self.ae.id)
        self.assertIsNone(existing.properties.csm)

        created = self._account("org-new")
        self.assertEqual(created.name, "Brand New")
        assert created.properties.csm is not None
        self.assertEqual(created.properties.csm.id, self.csm.id)
        self.assertIn("Created 1 account(s), updated 1", output)

    def test_blank_email_clears_role_but_unresolvable_email_is_left_untouched(self):
        account = create_account(team_id=self.team.id, name="Acme", external_id="org-1")
        account.properties = AccountProperties(
            csm=AccountAssignment(id=self.csm.id, email=self.csm.email),
            account_executive=AccountAssignment(id=self.ae.id, email=self.ae.email),
        )
        account.save(update_fields=["_properties"])

        csv_path = self._write_csv(
            [{"org_id": "org-1", "account_name": "Acme", "ae_email": "ghost@nowhere.com", "csm_email": ""}]
        )

        output = self._run(csv_path)

        account = self._account("org-1")
        # CSM was blank in the CSV: cleared. AE didn't resolve: left as-is and reported.
        self.assertIsNone(account.properties.csm)
        assert account.properties.account_executive is not None
        self.assertEqual(account.properties.account_executive.id, self.ae.id)
        self.assertIn("ghost@nowhere.com", output)

    def test_missing_account_without_create_flag_is_reported(self):
        csv_path = self._write_csv([{"org_id": "org-ghost", "account_name": "Ghost", "ae_email": "anna@x.com"}])

        output = self._run(csv_path)

        self.assertFalse(Account.objects.unscoped().filter(team_id=self.team.pk, external_id="org-ghost").exists())
        self.assertIn("org-ghost", output)
        self.assertIn("--create-missing", output)

    def test_dry_run_writes_nothing(self):
        create_account(team_id=self.team.id, name="Acme", external_id="org-1")
        csv_path = self._write_csv([{"org_id": "org-1", "account_name": "Acme", "ae_email": "anna@x.com"}])

        output = self._run(csv_path, dry_run=True)

        account = self._account("org-1")
        self.assertIsNone(account.properties.account_executive)
        self.assertIn("Dry run", output)

    def test_rejects_csv_with_missing_columns(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="")
        f.write("org_id,ae_email\norg-1,anna@x.com\n")
        f.close()
        self.addCleanup(os.unlink, f.name)

        with self.assertRaises(CommandError):
            self._run(f.name)
