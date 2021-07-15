from unittest import mock
from unittest.mock import Mock, patch

import pytest
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.celery import sync_all_organization_available_features
from posthog.models import Organization, OrganizationInvite, Plugin
from posthog.plugins.test.mock import mocked_plugin_requests_get
from posthog.plugins.test.plugin_archives import HELLO_WORLD_PLUGIN_GITHUB_ZIP
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

    @mock.patch("requests.get", side_effect=mocked_plugin_requests_get)
    def test_plugins_are_preinstalled_on_self_hosted(self, mock_get):
        with self.settings(
            MULTI_TENANCY=False, PLUGINS_PREINSTALLED_URLS=["https://github.com/PostHog/helloworldplugin/"]
        ):
            new_org, _, _ = Organization.objects.bootstrap(
                self.user, plugins_access_level=Organization.PluginsAccessLevel.INSTALL
            )

        self.assertEqual(
            Plugin.objects.filter(organization=new_org, is_preinstalled=True).count(), 1,
        )
        self.assertEqual(
            Plugin.objects.filter(organization=new_org, is_preinstalled=True).get().name, "helloworldplugin",
        )
        self.assertEqual(mock_get.call_count, 2)
        mock_get.assert_called_with(
            f"https://github.com/PostHog/helloworldplugin/archive/{HELLO_WORLD_PLUGIN_GITHUB_ZIP[0]}.zip", headers={}
        )

    @mock.patch("requests.get", side_effect=mocked_plugin_requests_get)
    def test_plugins_are_not_preinstalled_on_cloud(self, mock_get):
        with self.settings(
            MULTI_TENANCY=True, PLUGINS_PREINSTALLED_URLS=["https://github.com/PostHog/helloworldplugin/"]
        ):
            new_org, _, _ = Organization.objects.bootstrap(
                self.user, plugins_access_level=Organization.PluginsAccessLevel.INSTALL
            )

        self.assertEqual(Plugin.objects.filter(organization=new_org, is_preinstalled=True).count(), 0)
        self.assertEqual(mock_get.call_count, 0)

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

            # Still only old, empty available_features field value known
            self.assertFalse(self.organization.is_feature_available("whatever"))
            self.assertFalse(self.organization.is_feature_available("feature-doesnt-exist"))

            # New available_features field value that was updated in DB on license creation is known after refresh
            self.organization.refresh_from_db()
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
            sync_all_organization_available_features()  # This is normally ran every hour
            self.organization.refresh_from_db()
            self.assertFalse(self.organization.is_feature_available("whatever"))
