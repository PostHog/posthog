from unittest.mock import Mock, patch

import pytest
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.utils import timezone
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.models import Organization, OrganizationInvite, Plugin
from posthog.test.base import BaseTest


class TestOrganization(BaseTest):
    def test_organization_active_invites(self):
        self.assertEqual(self.organization.invites.count(), 0)
        self.assertEqual(self.organization.active_invites.count(), 0)

        OrganizationInvite.objects.create(organization=self.organization)
        self.assertEqual(self.organization.invites.count(), 1)
        self.assertEqual(self.organization.active_invites.count(), 1)

        expired_invite = OrganizationInvite.objects.create(organization=self.organization)
        OrganizationInvite.objects.filter(id=expired_invite.id).update(
            created_at=timezone.now() - timezone.timedelta(hours=73),
        )
        self.assertEqual(self.organization.invites.count(), 2)
        self.assertEqual(self.organization.active_invites.count(), 1)

    def test_plugins_are_preinstalled_on_self_hosted(self):
        with self.settings(TEST=False, MULTI_TENANCY=False):
            new_org, _, _ = Organization.objects.bootstrap(self.user)

        self.assertEqual(
            Plugin.objects.filter(organization=new_org, is_preinstalled=True).count(),
            len(settings.PLUGINS_PREINSTALLED_URLS),
        )

    def test_plugins_are_not_preinstalled_on_cloud(self):
        with self.settings(TEST=False, MULTI_TENANCY=True):
            new_org, _, _ = Organization.objects.bootstrap(self.user)

        self.assertEqual(
            Plugin.objects.filter(organization=new_org, is_preinstalled=True).count(), 0,
        )

    @pytest.mark.ee
    @patch("posthog.models.organization.License.PLANS", {"enterprise": ["whatever"]})
    @patch("ee.models.license.requests.post")
    def test_feature_available_self_hosted_has_license(self, patch_post):
        with self.settings(MULTI_TENANCY=False):
            from ee.models.license import License

            mock = Mock()
            mock.json.return_value = {"plan": "enterprise", "valid_until": now() + relativedelta(days=1)}
            patch_post.return_value = mock
            License.objects.create(key="key")
            self.assertTrue(self.organization.is_feature_available("whatever"))
            self.assertFalse(self.organization.is_feature_available("feature-doesnt-exist"))

    @pytest.mark.ee
    @patch("posthog.models.organization.License.PLANS", {"enterprise": ["whatever"]})
    def test_feature_available_self_hosted_no_license(self):
        self.assertFalse(self.organization.is_feature_available("whatever"))
        self.assertFalse(self.organization.is_feature_available("feature-doesnt-exist"))

    @pytest.mark.ee
    @patch("posthog.models.organization.License.PLANS", {"enterprise": ["whatever"]})
    @patch("ee.models.license.requests.post")
    def test_feature_available_self_hosted_license_expired(self, patch_post):
        from ee.models.license import License

        mock = Mock()
        mock.json.return_value = {"plan": "enterprise", "valid_until": "2012-01-14T12:00:00.000Z"}
        patch_post.return_value = mock
        License.objects.create(key="key")

        with freeze_time("2012-01-19T12:00:00.000Z"):
            self.assertFalse(self.organization.is_feature_available("whatever"))
