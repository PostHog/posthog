from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.schema import MaxBillingContextBillingPeriodInterval, MaxBillingContextSubscriptionLevel

from ee.hogai.context.billing import billing_response_to_max_context, fetch_server_billing_context


def _make_billing_response(
    *,
    subscription_level: str = "paid",
    has_active_subscription: bool = True,
    trial: dict | None = None,
    products: list | None = None,
    billing_period: dict | None = None,
    deactivated: bool = False,
) -> dict:
    return {
        "has_active_subscription": has_active_subscription,
        "subscription_level": subscription_level,
        "license": {"plan": "scale"},
        "deactivated": deactivated,
        "products": products or [],
        "billing_period": billing_period,
        "trial": trial,
        "current_total_amount_usd": "100.00",
        "projected_total_amount_usd": "200.00",
        "startup_program_label": None,
    }


class TestBillingResponseToMaxContext(BaseTest):
    @patch("ee.hogai.context.billing.HogFunction")
    def test_paid_subscription(self, mock_hog_function):
        mock_hog_function.objects.filter.return_value.count.return_value = 3
        billing_data = _make_billing_response(subscription_level="paid", has_active_subscription=True)
        result = billing_response_to_max_context(billing_data, self.team)

        self.assertEqual(result.subscription_level, MaxBillingContextSubscriptionLevel.PAID)
        self.assertTrue(result.has_active_subscription)
        self.assertEqual(result.billing_plan, "scale")
        self.assertFalse(result.is_deactivated)
        self.assertEqual(result.total_current_amount_usd, "100.00")
        self.assertEqual(result.projected_total_amount_usd, "200.00")
        self.assertIsNone(result.trial)
        self.assertIsNone(result.usage_history)
        self.assertIsNone(result.spend_history)

    @patch("ee.hogai.context.billing.HogFunction")
    def test_free_subscription(self, mock_hog_function):
        mock_hog_function.objects.filter.return_value.count.return_value = 0
        billing_data = _make_billing_response(subscription_level="free", has_active_subscription=False)
        result = billing_response_to_max_context(billing_data, self.team)

        self.assertEqual(result.subscription_level, MaxBillingContextSubscriptionLevel.FREE)
        self.assertFalse(result.has_active_subscription)

    @patch("ee.hogai.context.billing.HogFunction")
    def test_custom_subscription(self, mock_hog_function):
        mock_hog_function.objects.filter.return_value.count.return_value = 0
        billing_data = _make_billing_response(subscription_level="custom", has_active_subscription=True)
        result = billing_response_to_max_context(billing_data, self.team)

        self.assertEqual(result.subscription_level, MaxBillingContextSubscriptionLevel.CUSTOM)

    @patch("ee.hogai.context.billing.HogFunction")
    def test_unknown_subscription_level_defaults_to_free(self, mock_hog_function):
        mock_hog_function.objects.filter.return_value.count.return_value = 0
        billing_data = _make_billing_response(subscription_level="unknown_level")
        result = billing_response_to_max_context(billing_data, self.team)

        self.assertEqual(result.subscription_level, MaxBillingContextSubscriptionLevel.FREE)

    @patch("ee.hogai.context.billing.HogFunction")
    def test_active_trial(self, mock_hog_function):
        mock_hog_function.objects.filter.return_value.count.return_value = 0
        billing_data = _make_billing_response(
            subscription_level="free",
            has_active_subscription=False,
            trial={"status": "active", "expires_at": "2026-03-01", "target": "paid"},
        )
        result = billing_response_to_max_context(billing_data, self.team)

        self.assertIsNotNone(result.trial)
        self.assertTrue(result.trial.is_active)
        self.assertEqual(result.trial.expires_at, "2026-03-01")
        self.assertEqual(result.trial.target, "paid")

    @patch("ee.hogai.context.billing.HogFunction")
    def test_expired_trial(self, mock_hog_function):
        mock_hog_function.objects.filter.return_value.count.return_value = 0
        billing_data = _make_billing_response(
            trial={"status": "expired", "expires_at": "2025-01-01", "target": "paid"},
        )
        result = billing_response_to_max_context(billing_data, self.team)

        self.assertIsNotNone(result.trial)
        self.assertFalse(result.trial.is_active)

    @patch("ee.hogai.context.billing.HogFunction")
    def test_no_trial(self, mock_hog_function):
        mock_hog_function.objects.filter.return_value.count.return_value = 0
        billing_data = _make_billing_response(trial=None)
        result = billing_response_to_max_context(billing_data, self.team)

        self.assertIsNone(result.trial)

    @patch("ee.hogai.context.billing.HogFunction")
    def test_billing_period_monthly(self, mock_hog_function):
        mock_hog_function.objects.filter.return_value.count.return_value = 0
        billing_data = _make_billing_response(
            billing_period={
                "current_period_start": "2026-01-01",
                "current_period_end": "2026-01-31",
                "interval": "month",
            }
        )
        result = billing_response_to_max_context(billing_data, self.team)

        self.assertIsNotNone(result.billing_period)
        self.assertEqual(result.billing_period.current_period_start, "2026-01-01")
        self.assertEqual(result.billing_period.current_period_end, "2026-01-31")
        self.assertEqual(result.billing_period.interval, MaxBillingContextBillingPeriodInterval.MONTH)

    @patch("ee.hogai.context.billing.HogFunction")
    def test_billing_period_yearly(self, mock_hog_function):
        mock_hog_function.objects.filter.return_value.count.return_value = 0
        billing_data = _make_billing_response(
            billing_period={
                "current_period_start": "2025-01-01",
                "current_period_end": "2026-01-01",
                "interval": "year",
            }
        )
        result = billing_response_to_max_context(billing_data, self.team)

        self.assertEqual(result.billing_period.interval, MaxBillingContextBillingPeriodInterval.YEAR)

    @patch("ee.hogai.context.billing.HogFunction")
    def test_products_conversion(self, mock_hog_function):
        mock_hog_function.objects.filter.return_value.count.return_value = 0
        billing_data = _make_billing_response(
            products=[
                {
                    "type": "product_analytics",
                    "name": "Product analytics",
                    "description": "Track events",
                    "current_usage": 50000,
                    "usage_limit": 100000,
                    "percentage_usage": 0.5,
                    "projected_amount_usd": "400.00",
                    "docs_url": "https://posthog.com/docs",
                    "addons": [
                        {
                            "type": "group_analytics",
                            "name": "Group analytics",
                            "description": "Analyze by groups",
                            "current_usage": 1000,
                            "usage_limit": 5000,
                            "percentage_usage": 0.2,
                            "docs_url": "https://posthog.com/docs/groups",
                        }
                    ],
                }
            ]
        )
        result = billing_response_to_max_context(billing_data, self.team)

        self.assertEqual(len(result.products), 1)
        product = result.products[0]
        self.assertEqual(product.type, "product_analytics")
        self.assertEqual(product.name, "Product analytics")
        self.assertTrue(product.is_used)
        self.assertFalse(product.has_exceeded_limit)
        self.assertEqual(product.current_usage, 50000)
        self.assertEqual(product.percentage_usage, 0.5)

        self.assertEqual(len(product.addons), 1)
        addon = product.addons[0]
        self.assertEqual(addon.type, "group_analytics")
        self.assertTrue(addon.is_used)
        self.assertFalse(addon.has_exceeded_limit)

    @patch("ee.hogai.context.billing.HogFunction")
    def test_product_exceeded_limit(self, mock_hog_function):
        mock_hog_function.objects.filter.return_value.count.return_value = 0
        billing_data = _make_billing_response(
            products=[
                {
                    "type": "analytics",
                    "name": "Analytics",
                    "description": "desc",
                    "current_usage": 150000,
                    "usage_limit": 100000,
                    "percentage_usage": 1.5,
                    "addons": [],
                }
            ]
        )
        result = billing_response_to_max_context(billing_data, self.team)

        self.assertTrue(result.products[0].has_exceeded_limit)

    @patch("ee.hogai.context.billing.HogFunction")
    def test_product_not_used(self, mock_hog_function):
        mock_hog_function.objects.filter.return_value.count.return_value = 0
        billing_data = _make_billing_response(
            products=[
                {
                    "type": "replay",
                    "name": "Session replay",
                    "description": "desc",
                    "current_usage": 0,
                    "percentage_usage": 0,
                    "addons": [],
                }
            ]
        )
        result = billing_response_to_max_context(billing_data, self.team)

        self.assertFalse(result.products[0].is_used)

    @patch("ee.hogai.context.billing.HogFunction")
    def test_custom_limits_applied_to_products(self, mock_hog_function):
        mock_hog_function.objects.filter.return_value.count.return_value = 0
        billing_data = _make_billing_response(
            products=[
                {
                    "type": "product_analytics",
                    "name": "Product analytics",
                    "description": "desc",
                    "current_usage": 0,
                    "percentage_usage": 0,
                    "usage_key": "event_count_in_period",
                    "addons": [],
                }
            ]
        )
        billing_data["custom_limits_usd"] = {"product_analytics": 500.0}
        billing_data["next_period_custom_limits_usd"] = {"event_count_in_period": 600.0}

        result = billing_response_to_max_context(billing_data, self.team)

        self.assertEqual(result.products[0].custom_limit_usd, 500.0)
        self.assertEqual(result.products[0].next_period_custom_limit_usd, 600.0)

    @patch("ee.hogai.context.billing.HogFunction")
    def test_settings_from_team(self, mock_hog_function):
        mock_hog_function.objects.filter.return_value.count.return_value = 5
        self.team.autocapture_opt_out = True
        self.team.save()

        billing_data = _make_billing_response()
        result = billing_response_to_max_context(billing_data, self.team)

        self.assertFalse(result.settings.autocapture_on)
        self.assertEqual(result.settings.active_destinations, 5)

    @patch("ee.hogai.context.billing.HogFunction")
    def test_deactivated_account(self, mock_hog_function):
        mock_hog_function.objects.filter.return_value.count.return_value = 0
        billing_data = _make_billing_response(deactivated=True)
        result = billing_response_to_max_context(billing_data, self.team)

        self.assertTrue(result.is_deactivated)

    @patch("ee.hogai.context.billing.HogFunction")
    def test_minimal_response_no_optional_fields(self, mock_hog_function):
        mock_hog_function.objects.filter.return_value.count.return_value = 0
        billing_data = {
            "has_active_subscription": False,
            "products": [],
        }
        result = billing_response_to_max_context(billing_data, self.team)

        self.assertEqual(result.subscription_level, MaxBillingContextSubscriptionLevel.FREE)
        self.assertFalse(result.has_active_subscription)
        self.assertIsNone(result.billing_plan)
        self.assertIsNone(result.billing_period)
        self.assertIsNone(result.trial)
        self.assertEqual(result.products, [])


class TestFetchServerBillingContext(BaseTest):
    @patch("ee.hogai.context.billing.BillingManager")
    @patch("ee.hogai.context.billing.get_cached_instance_license")
    @patch("ee.hogai.context.billing.HogFunction")
    def test_returns_billing_context_on_success(self, mock_hog_function, mock_license_fn, mock_billing_cls):
        mock_hog_function.objects.filter.return_value.count.return_value = 0
        mock_license = MagicMock(is_v2_license=True)
        mock_license_fn.return_value = mock_license
        mock_billing_cls.return_value.get_billing.return_value = {
            "has_active_subscription": True,
            "subscription_level": "paid",
            "license": {"plan": "scale"},
            "products": [],
        }

        result = fetch_server_billing_context(self.team)

        self.assertIsNotNone(result)
        self.assertEqual(result.subscription_level, MaxBillingContextSubscriptionLevel.PAID)
        self.assertTrue(result.has_active_subscription)

    @patch("ee.hogai.context.billing.get_cached_instance_license")
    def test_returns_none_when_no_license(self, mock_license_fn):
        mock_license_fn.return_value = None
        result = fetch_server_billing_context(self.team)
        self.assertIsNone(result)

    @patch("ee.hogai.context.billing.get_cached_instance_license")
    def test_returns_none_when_not_v2_license(self, mock_license_fn):
        mock_license_fn.return_value = MagicMock(is_v2_license=False)
        result = fetch_server_billing_context(self.team)
        self.assertIsNone(result)

    @patch("ee.hogai.context.billing.BillingManager")
    @patch("ee.hogai.context.billing.get_cached_instance_license")
    def test_returns_none_on_billing_service_error(self, mock_license_fn, mock_billing_cls):
        mock_license_fn.return_value = MagicMock(is_v2_license=True)
        mock_billing_cls.return_value.get_billing.side_effect = Exception("Billing service error")

        result = fetch_server_billing_context(self.team)

        self.assertIsNone(result)
