from unittest.mock import Mock, call, patch

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time

from ee.models import License
from posthog.api.test.base import BaseTest
from posthog.models.user import User


class TestUser(BaseTest):
    TESTS_API = True

    @patch("posthog.models.user.EE_MISSING", True)
    def test_feature_available_no_ee(self):
        self.assertFalse(self.user.feature_available("whatever"))

    @patch("posthog.models.user.MULTI_TENANCY_MISSING", False)
    @patch("posthog.models.user.License.PLANS", {"price_1234567890": ["whatever"]})
    @patch("posthog.models.user.TeamBilling")
    def test_feature_available_multi_tenancy(self, patch_team_billing):
        patch_team_billing.objects.get().price_id = "price_1234567890"
        self.assertTrue(self.user.feature_available("whatever"))

    @patch("posthog.models.user.MULTI_TENANCY_MISSING", False)
    @patch("posthog.models.user.TeamBilling")
    def test_custom_pricing_no_extra_features(self, patch_team_billing):
        patch_team_billing.objects.get().price_id = (
            "price_test_1"  # price_test_1 is not on posthog.models.user.License.PLANS
        )
        self.assertFalse(self.user.feature_available("whatever"))

    @patch("posthog.models.user.License.PLANS", {"enterprise": ["whatever"]})
    @patch("ee.models.license.requests.post")
    @patch("posthog.models.user.MULTI_TENANCY_MISSING", True)
    def test_feature_available_self_hosted_has_license(self, patch_post):
        mock = Mock()
        mock.json.return_value = {"plan": "enterprise", "valid_until": now() + relativedelta(days=1)}
        patch_post.return_value = mock
        License.objects.create(key="key")
        self.assertTrue(self.user.feature_available("whatever"))
        self.assertFalse(self.user.feature_available("feature-doesnt-exist"))

    @patch("posthog.models.user.License.PLANS", {"enterprise": ["whatever"]})
    def test_feature_available_self_hosted_no_license(self):
        self.assertFalse(self.user.feature_available("whatever"))
        self.assertFalse(self.user.feature_available("feature-doesnt-exist"))

    @patch("posthog.models.user.License.PLANS", {"enterprise": ["whatever"]})
    @patch("ee.models.license.requests.post")
    def test_feature_available_self_hosted_license_expired(self, patch_post):
        mock = Mock()
        mock.json.return_value = {"plan": "enterprise", "valid_until": "2012-01-14T12:00:00.000Z"}
        patch_post.return_value = mock
        License.objects.create(key="key")

        with freeze_time("2012-01-19T12:00:00.000Z"):
            self.assertFalse(self.user.feature_available("whatever"))
