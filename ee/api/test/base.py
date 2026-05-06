import datetime
from typing import Optional, cast
from zoneinfo import ZoneInfo

from posthog.test.base import APIBaseTest

from posthog.constants import AvailableFeature

from ee.models.license import License, LicenseManager


class LicensedTestMixin:
    """
    Test API using Django REST Framework test suite, for licensed PostHog (mainly enterprise edition).
    """

    CONFIG_LICENSE_KEY: Optional[str] = "12345::67890"
    CONFIG_LICENSE_PLAN: Optional[str] = "enterprise"
    CONFIG_SYNC_ORGANIZATION_FEATURES_ON_SETUP: bool = True
    CONFIG_FORCE_ADVANCED_PERMISSIONS_ON_SETUP: bool = False
    license: License = cast(License, None)

    def license_required_response(
        self,
        message: str = "This feature is part of the premium PostHog offering. Self-hosted licenses are no longer available for purchase. Please contact sales@posthog.com to discuss options.",
    ) -> dict[str, Optional[str]]:
        return {
            "type": "server_error",
            "code": "payment_required",
            "detail": message,
            "attr": None,
        }

    @classmethod
    def setUpTestData(cls) -> None:
        parent_set_up_test_data = getattr(super(), "setUpTestData", None)
        if parent_set_up_test_data is not None:
            parent_set_up_test_data()
        if cls.CONFIG_LICENSE_PLAN:
            cls.license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
                key=cls.CONFIG_LICENSE_KEY,
                plan=cls.CONFIG_LICENSE_PLAN,
                valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7, tzinfo=ZoneInfo("UTC")),
            )
            if hasattr(cls, "organization") and cls.organization:
                cls.organization.update_available_product_features()
                cls.organization.save()


class APILicensedTest(LicensedTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()

        if not hasattr(self, "organization") or not self.organization:
            return

        if self.CONFIG_SYNC_ORGANIZATION_FEATURES_ON_SETUP:
            self.organization.update_available_product_features()
            self.organization.save()

        if self.CONFIG_FORCE_ADVANCED_PERMISSIONS_ON_SETUP and not self.organization.is_feature_available(
            AvailableFeature.ADVANCED_PERMISSIONS
        ):
            features = self.organization.available_product_features or []
            features.append(
                {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS}
            )
            self.organization.available_product_features = features
            self.organization.save()
