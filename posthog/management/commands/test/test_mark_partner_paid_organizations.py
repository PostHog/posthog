import uuid
import tempfile
from datetime import datetime
from io import StringIO
from pathlib import Path

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.utils import timezone

from posthog.models.oauth import OAuthApplication
from posthog.models.organization import Organization
from posthog.models.organization_provisioning import OrganizationProvisioning, get_billing_lock_partner


class TestMarkPartnerPaidOrganizations(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.paying_partner = self._create_partner("paying-partner", pays_for_customers=True)
        self.non_paying_partner = self._create_partner("non-paying-partner", pays_for_customers=False)

    def _create_partner(self, client_id: str, *, pays_for_customers: bool) -> OAuthApplication:
        partner = OAuthApplication.objects.create(
            client_id=client_id,
            name=client_id,
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://partner.example.com/callback",
            algorithm="RS256",
            is_provisioning_partner=True,
        )
        partner.update_provisioning(pays_for_customers=pays_for_customers)
        return partner

    def _provisioned_organization(self, partner: OAuthApplication | None) -> Organization:
        organization = Organization.objects.create(name="Partner organization", customer_id="cus_partner")
        OrganizationProvisioning.objects.create(
            organization=organization,
            partner=(
                OrganizationProvisioning.Partner.PROVISIONING_API
                if partner is not None
                else OrganizationProvisioning.Partner.VERCEL
            ),
            application=partner,
        )
        return organization

    def _run_command(self, *args: str) -> dict[str, str]:
        out = StringIO()
        call_command("mark_partner_paid_organizations", *args, stdout=out)
        return dict(line.rsplit(": ", 1) for line in out.getvalue().splitlines() if ": " in line)

    def _partner_paid_since(self, organization: Organization) -> datetime | None:
        return OrganizationProvisioning.objects.get(organization=organization).partner_paid_since

    def test_dry_run_counts_every_outcome_and_writes_nothing(self) -> None:
        unmarked = self._provisioned_organization(self.paying_partner)
        already_marked = self._provisioned_organization(self.paying_partner)
        OrganizationProvisioning.objects.filter(organization=already_marked).update(partner_paid_since=timezone.now())
        not_paying = self._provisioned_organization(self.non_paying_partner)
        vercel = self._provisioned_organization(None)
        unprovisioned = Organization.objects.create(name="Self-serve organization")

        with tempfile.TemporaryDirectory() as tmp_dir:
            ids_file = Path(tmp_dir) / "organization_ids.txt"
            ids_file.write_text(f"{unmarked.id}\n{already_marked.id},{not_paying.id}\n\n{uuid.uuid4()}\nnot-an-id\n")
            output = self._run_command(str(vercel.id), str(unprovisioned.id), str(unmarked.id), "--file", str(ids_file))

        assert output == {
            "would mark": "1",
            "already marked": "1",
            "no provisioning row": "1",
            "partner does not pay": "2",
            "not found": "1",
            "invalid id": "1",
        }
        assert self._partner_paid_since(unmarked) is None
        assert get_billing_lock_partner(unmarked) is None

    def test_apply_marks_once_and_keeps_the_lock_on(self) -> None:
        organization = self._provisioned_organization(self.paying_partner)

        first = self._run_command(str(organization.id), "--apply")
        marked_at = self._partner_paid_since(organization)
        second = self._run_command(str(organization.id), "--apply")

        assert (first["marked"], first["already marked"]) == ("1", "0")
        assert (second["marked"], second["already marked"]) == ("0", "1")
        assert marked_at is not None
        assert self._partner_paid_since(organization) == marked_at
        assert get_billing_lock_partner(organization) == self.paying_partner
