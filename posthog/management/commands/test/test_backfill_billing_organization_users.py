import csv
import uuid
import datetime
import tempfile
from io import StringIO
from pathlib import Path
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.db import OperationalError

import requests
from parameterized import parameterized

from posthog.cloud_utils import TEST_clear_instance_license_cache
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User

from ee.models.license import License, LicenseManager


class TestBackfillBillingOrganizationUsers(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        TEST_clear_instance_license_cache()
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="license_id::license_secret",
            plan="enterprise",
            valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
        )
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.tmp_dir = Path(tmp_dir.name)

    def _org_with_owner(self, name: str) -> Organization:
        organization = Organization.objects.create(name=name)
        User.objects.create_and_join(
            organization=organization,
            email=f"owner-{organization.id}@example.com",
            password=None,
            level=OrganizationMembership.Level.OWNER,
        )
        return organization

    def _run(self, org_ids: list[str], **options: str | int) -> tuple[str, str]:
        csv_path = self.tmp_dir / "orgs.csv"
        csv_path.write_text("org_id\n" + "".join(f"{org_id}\n" for org_id in org_ids))
        out, err = StringIO(), StringIO()
        call_command("backfill_billing_organization_users", str(csv_path), stdout=out, stderr=err, **options)
        return out.getvalue(), err.getvalue()

    @parameterized.expand(
        [
            ("ok", 200, None, None),
            ("unauthorized", 401, None, "billing returned 401"),
            ("not_found", 404, None, "billing returned 404"),
            ("server_error", 500, None, "billing returned 500"),
            ("raised", None, requests.ConnectionError("boom"), "ConnectionError: boom"),
        ]
    )
    @patch("ee.billing.billing_manager.http_session.patch")
    def test_reports_billing_outcome(self, _name, status_code, side_effect, expected_reason, mock_patch):
        organization = self._org_with_owner("Synced org")
        mock_patch.return_value = MagicMock(status_code=status_code, json=MagicMock(return_value={}))
        mock_patch.side_effect = side_effect

        out, err = self._run([str(organization.id)])

        mock_patch.assert_called_once()
        assert "Syncing 1 organizations with billing" in out
        if expected_reason is None:
            assert err == ""
            assert "Finished: 1 ok, 0 failed" in out
        else:
            assert f"FAILED {organization.id}: {expected_reason}" in err
            assert "Finished: 0 ok, 1 failed" in out
            assert f"Failed org ids: {organization.id}" in out

    @patch("posthog.management.commands.backfill_billing_organization_users.PROGRESS_EVERY", 2)
    @patch("ee.billing.billing_manager.http_session.patch")
    def test_offset_missing_org_no_owner_and_failed_csv(self, mock_patch):
        mock_patch.return_value = MagicMock(status_code=200, json=MagicMock(return_value={}))
        skipped = self._org_with_owner("Skipped by offset")
        synced = self._org_with_owner("Synced")
        ownerless = Organization.objects.create(name="No owner")
        missing_id = str(uuid.uuid4())
        failed_csv = self.tmp_dir / "failed.csv"

        out, err = self._run(
            [str(skipped.id), str(synced.id), missing_id, str(ownerless.id)],
            offset=1,
            failed_csv=str(failed_csv),
        )

        mock_patch.assert_called_once()
        assert mock_patch.call_args.kwargs["json"]["org_customer_email"] == f"owner-{synced.id}@example.com"
        assert "Syncing 3 organizations with billing" in out
        assert f"FAILED {missing_id}: organization not found" in err
        assert f"FAILED {ownerless.id}: organization has no owner" in err
        assert "Progress: 2/3 (1 failed)" in out
        assert "Finished: 1 ok, 2 failed" in out
        assert f"Failed org ids: {missing_id}, {ownerless.id}" in out
        with failed_csv.open() as f:
            assert list(csv.reader(f)) == [
                ["org_id", "reason"],
                [missing_id, "organization not found"],
                [str(ownerless.id), "organization has no owner"],
            ]

    @patch("ee.billing.billing_manager.http_session.patch")
    def test_database_error_fails_the_org_and_continues(self, mock_patch):
        mock_patch.return_value = MagicMock(status_code=200, json=MagicMock(return_value={}))
        first = self._org_with_owner("Lookup fails")
        second = self._org_with_owner("Synced")
        second_owner = User.objects.get(email=f"owner-{second.id}@example.com")

        with patch(
            "posthog.management.commands.backfill_billing_organization_users.get_most_recent_owner",
            side_effect=[OperationalError("statement timeout"), second_owner],
        ):
            out, err = self._run([str(first.id), str(second.id)])

        assert f"FAILED {first.id}: OperationalError: statement timeout" in err
        mock_patch.assert_called_once()
        assert "Finished: 1 ok, 1 failed" in out
