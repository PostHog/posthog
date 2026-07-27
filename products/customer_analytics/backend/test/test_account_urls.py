from unittest import TestCase

from parameterized import parameterized

from products.customer_analytics.backend.account_urls import build_account_deeplink


class TestBuildAccountDeeplink(TestCase):
    def test_id_only_omits_tab(self):
        assert build_account_deeplink(account_id="acc-1") == "/customer_analytics/accounts/acc-1"

    def test_with_tab(self):
        assert build_account_deeplink(account_id="acc-1", tab="usage") == "/customer_analytics/accounts/acc-1/usage"

    @parameterized.expand([(None,), ("",)])
    def test_falsy_tab_is_omitted(self, tab):
        assert build_account_deeplink(account_id="acc-1", tab=tab) == "/customer_analytics/accounts/acc-1"

    def test_special_characters_are_percent_encoded(self):
        assert build_account_deeplink(account_id="a/b", tab="x y") == "/customer_analytics/accounts/a%2Fb/x%20y"
