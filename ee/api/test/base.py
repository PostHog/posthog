from typing import Optional

from django.utils import timezone

from ee.models.license import License
from posthog.api.test.base import APIBaseTest, BaseTest, TransactionBaseTest


class APILicensedTest(APIBaseTest):
    """
    Test API using Django REST Framework test suite, for licensed PostHog (mainly enterprise edition).
    """

    CONFIG_LICENSE_PLAN: Optional[str] = "enterprise"

    def setUp(self):
        super().setUp()
        if self.CONFIG_LICENSE_PLAN:
            self.license = License.objects._create(
                key=self.CONFIG_LICENSE_PLAN,
                plan=self.CONFIG_LICENSE_PLAN,
                valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7),
            )
