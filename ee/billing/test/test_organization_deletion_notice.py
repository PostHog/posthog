import datetime
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

import jwt

from ee.billing.billing_manager import (
    BillingManager,
    notify_billing_organization_deleted,
    organization_has_active_subscription,
)
from ee.models.license import License, LicenseManager


def _create_license() -> License:
    return super(LicenseManager, cast(LicenseManager, License.objects)).create(
        key="key123::secret123",
        plan="enterprise",
        valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
    )


class TestMarkOrganizationsDeleted(BaseTest):
    def setUp(self):
        super().setUp()
        self.license = _create_license()

    @patch(
        "ee.billing.billing_manager.http_session.post",
        return_value=MagicMock(
            status_code=200, json=MagicMock(return_value={"marked": 1, "already_marked": 0, "not_found": []})
        ),
    )
    def test_posts_the_ids_with_an_org_less_action_scoped_token(self, post_mock):
        result = BillingManager(self.license).mark_organizations_deleted(["org-1"])

        assert result == {"marked": 1, "already_marked": 0, "not_found": []}
        (url,) = post_mock.call_args.args
        assert url == "https://billing.posthog.com/api/internal/deleted-organizations"
        assert post_mock.call_args.kwargs["json"] == {"organization_ids": ["org-1"]}
        token = post_mock.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        payload = jwt.decode(token, "secret123", algorithms=["HS256"], audience="posthog:license-key")
        assert payload["service_action"] == "deleted_organizations"
        assert "organization_id" not in payload

    @patch(
        "ee.billing.billing_manager.http_session.post",
        return_value=MagicMock(status_code=404, json=MagicMock(return_value={"detail": "not found"})),
    )
    def test_raises_when_billing_does_not_confirm(self, post_mock):
        # A 404 means the endpoint is not deployed; the caller must not read it as a delivered notice.
        with self.assertRaises(Exception):
            BillingManager(self.license).mark_organizations_deleted(["org-1"])


class TestNotifyBillingOrganizationDeleted(BaseTest):
    @patch("ee.billing.billing_manager.BillingManager.mark_organizations_deleted")
    @patch("ee.billing.billing_manager.get_cached_instance_license")
    def test_notifies_on_cloud(self, license_mock, mark_mock):
        license_mock.return_value = _create_license()

        with self.is_cloud(True):
            notify_billing_organization_deleted("org-1")

        mark_mock.assert_called_once_with(["org-1"])

    @patch("ee.billing.billing_manager.BillingManager.mark_organizations_deleted")
    @patch("ee.billing.billing_manager.get_cached_instance_license")
    def test_skips_self_hosted_and_missing_license(self, license_mock, mark_mock):
        license_mock.return_value = _create_license()
        with self.is_cloud(False):
            notify_billing_organization_deleted("org-1")

        license_mock.return_value = None
        with self.is_cloud(True):
            notify_billing_organization_deleted("org-1")

        mark_mock.assert_not_called()


class TestOrganizationHasActiveSubscription(BaseTest):
    @patch("ee.billing.billing_manager.BillingManager.get_billing")
    @patch("ee.billing.billing_manager.get_cached_instance_license")
    def test_reads_the_billing_status_on_cloud(self, license_mock, get_billing_mock):
        license_mock.return_value = _create_license()
        for reported, expected in ((True, True), (False, False), (None, False)):
            get_billing_mock.return_value = {"has_active_subscription": reported}
            with self.is_cloud(True):
                assert organization_has_active_subscription(self.organization) is expected

    @patch("ee.billing.billing_manager.BillingManager.get_billing")
    @patch("ee.billing.billing_manager.get_cached_instance_license")
    def test_is_false_without_cloud_billing(self, license_mock, get_billing_mock):
        license_mock.return_value = _create_license()
        with self.is_cloud(False):
            assert organization_has_active_subscription(self.organization) is False

        license_mock.return_value = None
        with self.is_cloud(True):
            assert organization_has_active_subscription(self.organization) is False

        get_billing_mock.assert_not_called()
