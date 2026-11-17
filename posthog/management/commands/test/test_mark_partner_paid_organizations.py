import uuid
import tempfile
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

from unittest.mock import patch

from django.core.management import call_command
from django.utils import timezone

from posthog.management.commands import mark_partner_paid_organizations as command
from posthog.models.organization import Organization
from posthog.models.organization_provisioning import (
    OrganizationProvisioning,
    get_billing_lock_partner,
    mark_partner_paid,
)

from ee.api.agentic_provisioning.test.base import ProvisioningTestBase


class TestMarkPartnerPaidOrganizations(ProvisioningTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.partner.update_provisioning(pays_for_customers=True)

    def _partner_organization(self, *, marked: bool = False) -> Organization:
        organization = Organization.objects.create(name="Partner organization", customer_id="cus_partner")
        OrganizationProvisioning.objects.create(
            organization=organization,
            partner=OrganizationProvisioning.Partner.PROVISIONING_API,
            application=self.partner,
            partner_paid_since=timezone.now() if marked else None,
        )
        return organization

    def _vercel_organization(self) -> Organization:
        organization = Organization.objects.create(name="Vercel organization")
        OrganizationProvisioning.objects.create(
            organization=organization, partner=OrganizationProvisioning.Partner.VERCEL
        )
        return organization

    def _run_command(self, *args: str) -> dict[str, list[str]]:
        out = StringIO()
        call_command("mark_partner_paid_organizations", *args, stdout=out)
        report: dict[str, list[str]] = {}
        counts: dict[str, int] = {}
        label = ""
        for line in out.getvalue().splitlines()[1:]:
            if line.startswith("  "):
                report[label] = line.strip().split(", ")
            else:
                label, count = line.rsplit(": ", 1)
                report[label], counts[label] = [], int(count)
        assert counts == {label: len(ids) for label, ids in report.items()}
        return report

    def _partner_paid_since(self, organization: Organization) -> datetime | None:
        return OrganizationProvisioning.objects.get(organization=organization).partner_paid_since

    def test_dry_run_lists_the_ids_for_every_outcome_and_writes_nothing(self) -> None:
        unmarked = self._partner_organization()
        marked = self._partner_organization(marked=True)
        vercel = self._vercel_organization()
        unprovisioned = Organization.objects.create(name="Self-serve organization")
        missing = uuid.uuid4()

        with tempfile.TemporaryDirectory() as tmp_dir:
            ids_file = Path(tmp_dir) / "organization_ids.txt"
            ids_file.write_text(f"{unmarked.id}\n{marked.id},{vercel.id}\n\n{missing}\nnot-an-id\n")
            report = self._run_command(str(unprovisioned.id), str(unmarked.id), "--file", str(ids_file))

        assert report == {
            "would mark": [str(unmarked.id)],
            "already marked": [str(marked.id)],
            "partner does not pay": [str(vercel.id)],
            "no provisioning row": [str(unprovisioned.id)],
            "not found": [str(missing)],
            "invalid id": ["not-an-id"],
            "skipped, changed during run": [],
        }
        assert self._partner_paid_since(unmarked) is None
        assert get_billing_lock_partner(unmarked) is None

    def test_apply_marks_once_and_keeps_the_lock_on(self) -> None:
        organization = self._partner_organization()

        first = self._run_command(str(organization.id), "--apply")
        marked_at = self._partner_paid_since(organization)
        second = self._run_command(str(organization.id), "--apply")

        assert (first["marked"], first["already marked"]) == ([str(organization.id)], [])
        assert (second["marked"], second["already marked"]) == ([], [str(organization.id)])
        assert marked_at is not None
        assert self._partner_paid_since(organization) == marked_at
        assert get_billing_lock_partner(organization) == self.partner

    def test_apply_reports_an_organization_that_billing_marked_during_the_run(self) -> None:
        organization = self._partner_organization()
        classify = command.classify

        def classify_then_sync(**kwargs: Any) -> command.Outcome:
            outcome = classify(**kwargs)
            mark_partner_paid([organization.id])
            return outcome

        with patch.object(command, "classify", side_effect=classify_then_sync):
            report = self._run_command(str(organization.id), "--apply")

        assert (report["marked"], report["skipped, changed during run"]) == ([], [str(organization.id)])

    def test_unmark_releases_the_lock_only_with_apply(self) -> None:
        marked = self._partner_organization(marked=True)
        unmarked = self._partner_organization()

        dry_run = self._run_command("--unmark", str(marked.id), str(unmarked.id))
        locked_after_dry_run = get_billing_lock_partner(marked)
        applied = self._run_command("--unmark", str(marked.id), str(unmarked.id), "--apply")

        assert (dry_run["would unmark"], dry_run["not marked"]) == ([str(marked.id)], [str(unmarked.id)])
        assert locked_after_dry_run == self.partner
        assert (applied["unmarked"], applied["not marked"]) == ([str(marked.id)], [str(unmarked.id)])
        assert self._partner_paid_since(marked) is None
        assert get_billing_lock_partner(marked) is None
