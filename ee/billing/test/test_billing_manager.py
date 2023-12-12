from typing import cast
from unittest.mock import MagicMock, patch

from django.utils import timezone

from ee.billing.billing_manager import BillingManager
from ee.models.license import License, LicenseManager
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.test.base import BaseTest


class TestBillingManager(BaseTest):
    @patch(
        "ee.billing.billing_manager.requests.patch",
        return_value=MagicMock(status_code=200, json=MagicMock(return_value={"text": "ok"})),
    )
    def test_update_billing_distinct_ids(self, billing_patch_request_mock: MagicMock):
        organization = self.organization
        license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key123::key123",
            plan="enterprise",
            valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7),
        )
        User.objects.create_and_join(
            organization=organization,
            email="y@x.com",
            password=None,
            level=OrganizationMembership.Level.ADMIN,
        )
        organization.refresh_from_db()
        assert len(organization.members.values_list("distinct_id", flat=True)) == 2  # one exists in the test base
        BillingManager(license).update_billing_distinct_ids(organization)
        assert billing_patch_request_mock.call_count == 1
        assert len(billing_patch_request_mock.call_args[1]["json"]["distinct_ids"]) == 2

    @patch(
        "ee.billing.billing_manager.requests.patch",
        return_value=MagicMock(status_code=200, json=MagicMock(return_value={"text": "ok"})),
    )
    def test_update_billing_customer_email(self, billing_patch_request_mock: MagicMock):
        organization = self.organization
        license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key123::key123",
            plan="enterprise",
            valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7),
        )
        User.objects.create_and_join(
            organization=organization,
            email="y@x.com",
            password=None,
            level=OrganizationMembership.Level.OWNER,
        )
        organization.refresh_from_db()
        assert len(organization.members.values_list("distinct_id", flat=True)) == 2  # one exists in the test base
        BillingManager(license).update_billing_customer_email(organization)
        assert billing_patch_request_mock.call_count == 1
        assert billing_patch_request_mock.call_args[1]["json"]["org_customer_email"] == "y@x.com"
