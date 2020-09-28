from unittest.mock import Mock, call, patch

from dateutil.relativedelta import relativedelta
from django.test import tag
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.api.test.base import BaseTest
from posthog.models.user import User


class TestUser(BaseTest):
    TESTS_API = True

    @patch("posthog.settings.EE_AVAILABLE", False)
    def test_feature_available_no_ee(self):
        self.assertFalse(self.user.is_feature_available("whatever"))

    @tag("ee")
    @patch("posthog.models.user.License.PLANS", {"enterprise": ["whatever"]})
    @patch("ee.models.license.requests.post")
    @patch("posthog.models.user.MULTI_TENANCY_MISSING", True)
    def test_feature_available_self_hosted_has_license(self, patch_post):
        from ee.models import License

        mock = Mock()
        mock.json.return_value = {"plan": "enterprise", "valid_until": now() + relativedelta(days=1)}
        patch_post.return_value = mock
        License.objects.create(key="key")
        self.assertTrue(self.user.is_feature_available("whatever"))
        self.assertFalse(self.user.is_feature_available("feature-doesnt-exist"))

    @tag("ee")
    @patch("posthog.models.user.License.PLANS", {"enterprise": ["whatever"]})
    def test_feature_available_self_hosted_no_license(self):
        self.assertFalse(self.user.is_feature_available("whatever"))
        self.assertFalse(self.user.is_feature_available("feature-doesnt-exist"))

    @tag("ee")
    @patch("posthog.models.user.License.PLANS", {"enterprise": ["whatever"]})
    @patch("ee.models.license.requests.post")
    def test_feature_available_self_hosted_license_expired(self, patch_post):
        from ee.models import License

        mock = Mock()
        mock.json.return_value = {"plan": "enterprise", "valid_until": "2012-01-14T12:00:00.000Z"}
        patch_post.return_value = mock
        License.objects.create(key="key")

        with freeze_time("2012-01-19T12:00:00.000Z"):
            self.assertFalse(self.user.is_feature_available("whatever"))
