from typing import Any, cast
from unittest.mock import MagicMock, patch

from django.utils import timezone

from ee.billing.billing_manager import BillingManager
from ee.billing.billing_types import Product
from ee.models.license import License, LicenseManager
from posthog.cloud_utils import TEST_clear_instance_license_cache
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.test.base import BaseTest


def create_default_products_response(**kwargs) -> dict[str, list[Product]]:
    data: Any = {
        "products": [
            Product(
                name="Product analytics",
                headline="Product analytics with autocapture",
                description="A comprehensive product analytics platform built to natively work with session replay, feature flags, A/B testing, and surveys.",
                usage_key="events",
                image_url="https://posthog.com/images/products/product-analytics/product-analytics.png",
                docs_url="https://posthog.com/docs/product-analytics",
                type="product_analytics",
                unit="event",
                contact_support=False,
                inclusion_only=False,
                icon_key="IconGraph",
                plans=[],
                addons=[],
            )
        ]
    }

    data.update(kwargs)
    return data


class TestBillingManager(BaseTest):
    @patch(
        "ee.billing.billing_manager.requests.get",
        return_value=MagicMock(
            status_code=200, json=MagicMock(return_value={"products": create_default_products_response()})
        ),
    )
    def test_get_billing_unlicensed(self, billing_patch_request_mock):
        organization = self.organization
        TEST_clear_instance_license_cache()

        BillingManager(license=None).get_billing(organization, plan_keys=None)
        assert billing_patch_request_mock.call_count == 1
        billing_patch_request_mock.assert_called_with(
            "https://billing.posthog.com/api/products-v2", params={"plan": "standard"}, headers={}
        )

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

    @patch(
        "ee.billing.billing_manager.requests.patch",
        return_value=MagicMock(status_code=200, json=MagicMock(return_value={"text": "ok"})),
    )
    def test_update_billing_admin_emails(self, billing_patch_request_mock: MagicMock):
        organization = self.organization
        license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key123::key123",
            plan="enterprise",
            valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7),
        )
        User.objects.create_and_join(
            organization=organization,
            email="y1@x.com",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )
        User.objects.create_and_join(
            organization=organization,
            email="y2@x.com",
            password=None,
            level=OrganizationMembership.Level.ADMIN,
        )
        User.objects.create_and_join(
            organization=organization,
            email="y3@x.com",
            password=None,
            level=OrganizationMembership.Level.OWNER,
        )
        organization.refresh_from_db()
        BillingManager(license).update_billing_admin_emails(organization)
        assert billing_patch_request_mock.call_count == 1
        assert billing_patch_request_mock.call_args[1]["json"]["org_admin_emails"] == ["y2@x.com", "y3@x.com"]
