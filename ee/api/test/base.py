from typing import Optional, cast

from django.utils import timezone

from ee.models.license import License, LicenseManager
from posthog.test.base import APIBaseTest, APITransactionBaseTest


class LicensedTestMixin:
    """
    Test API using Django REST Framework test suite, for licensed PostHog (mainly enterprise edition).
    """

    CONFIG_LICENSE_PLAN: Optional[str] = "enterprise"

    def setUp(self):
        super().setUp()  # type: ignore
        if self.CONFIG_LICENSE_PLAN:
            self.license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
                key=self.CONFIG_LICENSE_PLAN,
                plan=self.CONFIG_LICENSE_PLAN,
                valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7),
            )


class APILicensedTest(LicensedTestMixin, APIBaseTest):
    pass


class APITransactionLicensedTest(LicensedTestMixin, APITransactionBaseTest):
    pass
