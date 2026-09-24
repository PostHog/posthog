from datetime import timedelta

import time_machine

from django.test import TestCase
from django.utils import timezone

from parameterized import parameterized

from ee.models.license import License


class TestLicenseManager(TestCase):
    @parameterized.expand(
        [
            ("scale_then_enterprise", [License.SCALE_PLAN, License.ENTERPRISE_PLAN]),
            ("enterprise_then_scale", [License.ENTERPRISE_PLAN, License.SCALE_PLAN]),
        ]
    )
    @time_machine.travel("2022-06-03T12:00:00Z", tick=False)
    def test_first_valid_returns_highest_plan_regardless_of_creation_order(self, _name, creation_order):
        licenses = {}
        for index, plan in enumerate(creation_order):
            with time_machine.travel(timezone.now() + timedelta(days=index), tick=False):
                licenses[plan] = License.objects.create(
                    key=f"{plan}-license",
                    plan=plan,
                    valid_until=timezone.now() + timedelta(days=30),
                )

        self.assertEqual(License.objects.first_valid(), licenses[License.ENTERPRISE_PLAN])
