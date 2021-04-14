from typing import Optional, cast

from django.utils import timezone

from ee.models.license import License, LicenseManager
from posthog.test.base import APIBaseTest


class LicensedTestMixin:
    """
    Test API using Django REST Framework test suite, for licensed PostHog (mainly enterprise edition).
    """

    CONFIG_LICENSE_PLAN: Optional[str] = "enterprise"
    license: License = None  # type: ignore

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()  # type: ignore
        if cls.CONFIG_LICENSE_PLAN:
            cls.license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
                key=cls.CONFIG_LICENSE_PLAN,
                plan=cls.CONFIG_LICENSE_PLAN,
                valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7),
            )


class APILicensedTest(LicensedTestMixin, APIBaseTest):
    pass
