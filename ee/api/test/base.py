import datetime
from typing import Dict, Optional, cast

from zoneinfo import ZoneInfo

from ee.api.test.fixtures.available_product_features import AVAILABLE_PRODUCT_FEATURES
from ee.models.license import License, LicenseManager
from posthog.test.base import APIBaseTest


class LicensedTestMixin:
    """
    Test API using Django REST Framework test suite, for licensed PostHog (mainly enterprise edition).
    """

    CONFIG_LICENSE_KEY: Optional[str] = "12345::67890"
    CONFIG_LICENSE_PLAN: Optional[str] = "enterprise"
    license: License = None  # type: ignore

    def license_required_response(
        self,
        message: str = "This feature is part of the premium PostHog offering. Self-hosted licenses are no longer available for purchase. Please contact sales@posthog.com to discuss options.",
    ) -> Dict[str, Optional[str]]:
        return {
            "type": "server_error",
            "code": "payment_required",
            "detail": message,
            "attr": None,
        }

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()  # type: ignore
        if cls.CONFIG_LICENSE_PLAN:
            cls.license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
                key=cls.CONFIG_LICENSE_KEY,
                plan=cls.CONFIG_LICENSE_PLAN,
                valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7, tzinfo=ZoneInfo("UTC")),
            )
            if hasattr(cls, "organization") and cls.organization:  # type: ignore
                cls.organization.available_product_features = AVAILABLE_PRODUCT_FEATURES  # type: ignore
                cls.organization.update_available_features()  # type: ignore
                cls.organization.save()  # type: ignore


class APILicensedTest(LicensedTestMixin, APIBaseTest):
    pass
