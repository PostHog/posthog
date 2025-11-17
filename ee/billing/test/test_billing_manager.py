from typing import Any, cast

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.cloud_utils import TEST_clear_instance_license_cache
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from ee.billing.billing_manager import BillingManager
from ee.billing.billing_types import Product
from ee.models.license import License, LicenseManager


def create_default_products_response(**kwargs) -> dict[str, list[Product]]:
    data: Any = {
        "products": [
            Product(
                name="Product analytics",
                headline="Product analytics with autocapture",
                description="A comprehensive product analytics platform built to natively work with session replay, feature flags, experiments, and surveys.",
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

        BillingManager(license=None).get_billing(organization)
        assert billing_patch_request_mock.call_count == 1
        billing_patch_request_mock.assert_called_with(
            "https://billing.posthog.com/api/products-v2", params={"plan": "standard"}, headers={}
        )

    @patch(
        "ee.billing.billing_manager.requests.patch",
        return_value=MagicMock(status_code=200, json=MagicMock(return_value={"text": "ok"})),
    )
    def test_update_billing_organization_users(self, billing_patch_request_mock: MagicMock):
        organization = self.organization
        license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key123::key123",
            plan="enterprise",
            valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7),
        )
        y = User.objects.create_and_join(
            organization=organization,
            email="y@x.com",
            password=None,
            level=OrganizationMembership.Level.OWNER,
        )
        organization.refresh_from_db()
        assert len(organization.members.values_list("distinct_id", flat=True)) == 2  # one exists in the test base
        BillingManager(license).update_billing_organization_users(organization)
        assert billing_patch_request_mock.call_count == 1
        assert len(billing_patch_request_mock.call_args[1]["json"]["distinct_ids"]) == 2
        assert billing_patch_request_mock.call_args[1]["json"]["org_customer_email"] == "y@x.com"
        assert billing_patch_request_mock.call_args[1]["json"]["org_admin_emails"] == ["y@x.com"]
        assert billing_patch_request_mock.call_args[1]["json"]["org_users"] == [
            {"email": "y@x.com", "distinct_id": y.distinct_id, "role": 15},
        ]

    @patch(
        "ee.billing.billing_manager.requests.patch",
        return_value=MagicMock(status_code=200, json=MagicMock(return_value={"text": "ok"})),
    )
    def test_update_billing_organization_users_with_multiple_members(self, billing_patch_request_mock: MagicMock):
        organization = self.organization
        license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key123::key123",
            plan="enterprise",
            valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7),
        )
        User.objects.create_and_join(
            organization=organization,
            email="y1@x.com",
            first_name="y1",
            last_name="y1",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )
        y2 = User.objects.create_and_join(
            organization=organization,
            email="y2@x.com",
            first_name="y2",
            last_name="y2",
            password=None,
            level=OrganizationMembership.Level.ADMIN,
        )
        y3 = User.objects.create_and_join(
            organization=organization,
            email="y3@x.com",
            password=None,
            level=OrganizationMembership.Level.OWNER,
        )
        organization.refresh_from_db()
        BillingManager(license).update_billing_organization_users(organization)
        assert billing_patch_request_mock.call_count == 1
        assert len(billing_patch_request_mock.call_args[1]["json"]["distinct_ids"]) == 4
        assert billing_patch_request_mock.call_args[1]["json"]["org_customer_email"] == "y3@x.com"
        assert sorted(billing_patch_request_mock.call_args[1]["json"]["org_admin_emails"]) == ["y2@x.com", "y3@x.com"]
        assert billing_patch_request_mock.call_args[1]["json"]["org_users"] == [
            {"email": "y2@x.com", "distinct_id": y2.distinct_id, "role": 8},
            {"email": "y3@x.com", "distinct_id": y3.distinct_id, "role": 15},
        ]

    @patch("posthoganalytics.capture")
    def test_update_org_details_preserves_quota_limits(self, patch_capture):
        organization = self.organization
        organization.usage = {
            "events": {
                "usage": 90,
                "limit": 1000,
                "todays_usage": 10,
                "quota_limited_until": 1612137599,
            },
            "exceptions": {
                "usage": 10,
                "limit": 100,
                "todays_usage": 5,
                "quota_limiting_suspended_until": 1611705600,
            },
            "recordings": {
                "usage": 15,
                "limit": 100,
                "todays_usage": 5,
                "quota_limiting_suspended_until": 1611705600,
            },
            "rows_synced": {"usage": 45, "limit": 500, "todays_usage": 5},
            "rows_exported": {"usage": 10, "limit": 1000, "todays_usage": 5},
            "feature_flag_requests": {"usage": 25, "limit": 300, "todays_usage": 5},
            "api_queries_read_bytes": {"usage": 1000, "limit": 1000000, "todays_usage": 500},
            "llm_events": {"usage": 50, "limit": 1000, "todays_usage": 2},
            "cdp_trigger_events": {"usage": 10, "limit": 100, "todays_usage": 5},
            "period": ["2024-01-01T00:00:00Z", "2024-01-31T23:59:59Z"],
            "survey_responses": {
                "usage": 10,
                "limit": 100,
                "todays_usage": 5,
                "quota_limiting_suspended_until": 1611705600,
            },
        }
        organization.save()

        license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key123::key123",
            plan="enterprise",
            valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7),
        )

        billing_status = {
            "customer": {
                "usage_summary": {
                    "events": {"usage": 90, "limit": 1000},
                    "exceptions": {"usage": 10, "limit": 100},
                    "recordings": {"usage": 15, "limit": 100},
                    "rows_synced": {"usage": 45, "limit": 500},
                    "rows_exported": {"usage": 10, "limit": 1000},
                    "feature_flag_requests": {"usage": 25, "limit": 300},
                    "api_queries_read_bytes": {"usage": 1000, "limit": 1000000},
                    "llm_events": {"usage": 50, "limit": 1000},
                    "survey_responses": {"usage": 10, "limit": 100},
                    "cdp_trigger_events": {"usage": 10, "limit": 100},
                },
                "billing_period": {
                    "current_period_start": "2024-01-01T00:00:00Z",
                    "current_period_end": "2024-01-31T23:59:59Z",
                },
            }
        }

        BillingManager(license).update_org_details(organization, billing_status)
        organization.refresh_from_db()

        assert organization.usage == {
            "events": {
                "usage": 90,
                "limit": 1000,
                "todays_usage": 10,
                "quota_limited_until": 1612137599,
            },
            "exceptions": {
                "usage": 10,
                "limit": 100,
                "todays_usage": 5,
                "quota_limiting_suspended_until": 1611705600,
            },
            "recordings": {
                "usage": 15,
                "limit": 100,
                "todays_usage": 5,
                "quota_limiting_suspended_until": 1611705600,
            },
            "rows_synced": {"usage": 45, "limit": 500, "todays_usage": 5},
            "rows_exported": {"usage": 10, "limit": 1000, "todays_usage": 5},
            "feature_flag_requests": {"usage": 25, "limit": 300, "todays_usage": 5},
            "llm_events": {"usage": 50, "limit": 1000, "todays_usage": 2},
            "period": ["2024-01-01T00:00:00Z", "2024-01-31T23:59:59Z"],
            "api_queries_read_bytes": {"usage": 1000, "limit": 1000000, "todays_usage": 500},
            "cdp_trigger_events": {"usage": 10, "limit": 100, "todays_usage": 5},
            "survey_responses": {
                "usage": 10,
                "limit": 100,
                "todays_usage": 5,
                "quota_limiting_suspended_until": 1611705600,
            },
        }
