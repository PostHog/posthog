from datetime import datetime, timedelta

from freezegun import freeze_time

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.activity_logging.retention import get_activity_log_lookback_restriction
from posthog.models.organization import Organization

NOW = datetime(2026, 6, 1, 12, 0, 0)


class TestActivityLogLookbackWindow(SimpleTestCase):
    @parameterized.expand(
        [
            ("boost", {"limit": 7, "unit": "days"}, 7),
            ("scale", {"limit": 2, "unit": "months"}, 60),
            ("enterprise", {"limit": 60, "unit": "months"}, 1800),
            ("singular unit", {"limit": 1, "unit": "year"}, 365),
            # Billing sent the feature without a window. Falling back to anything wider than the
            # smallest plan would read a Boost organization past what it bought.
            ("no window falls back to the smallest plan", {}, 7),
            # An unrecognized unit must not raise: both readers run outside HogQL's error handling,
            # so raising 500s every query naming system.activity_logs instead of restricting it.
            ("unknown unit falls back to the smallest plan", {"limit": 3, "unit": "weeks"}, 7),
        ]
    )
    def test_window_for_entitlement(self, _name: str, feature: dict, expected_days: int):
        organization = Organization(available_product_features=[{"key": "audit_logs", **feature}])

        with freeze_time(NOW):
            restriction = get_activity_log_lookback_restriction(organization)

        assert restriction is not None
        self.assertEqual(NOW - restriction.replace(tzinfo=None), timedelta(days=expected_days))

    def test_no_entitlement_is_unrestricted(self):
        organization = Organization(available_product_features=[])

        self.assertIsNone(get_activity_log_lookback_restriction(organization))
