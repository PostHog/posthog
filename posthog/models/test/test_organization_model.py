from posthog.test.base import BaseTest
from unittest import mock
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from posthog.models import Organization, OrganizationInvite, Plugin
from posthog.models.organization import OrganizationMembership
from posthog.plugins.test.mock import mocked_plugin_requests_get
from posthog.plugins.test.plugin_archives import HELLO_WORLD_PLUGIN_GITHUB_ZIP


class TestOrganization(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_organization_active_invites(self):
        self.assertEqual(self.organization.invites.count(), 0)
        self.assertEqual(self.organization.active_invites.count(), 0)

        OrganizationInvite.objects.create(organization=self.organization)
        self.assertEqual(self.organization.invites.count(), 1)
        self.assertEqual(self.organization.active_invites.count(), 1)

        expired_invite = OrganizationInvite.objects.create(organization=self.organization)
        OrganizationInvite.objects.filter(id=expired_invite.id).update(
            created_at=timezone.now() - timezone.timedelta(hours=73)
        )
        self.assertEqual(self.organization.invites.count(), 2)
        self.assertEqual(self.organization.active_invites.count(), 1)

    @mock.patch("requests.get", side_effect=mocked_plugin_requests_get)
    def test_plugins_are_preinstalled_on_self_hosted(self, mock_get):
        with self.is_cloud(False):
            with self.settings(PLUGINS_PREINSTALLED_URLS=["https://github.com/PostHog/helloworldplugin/"]):
                new_org, _, _ = Organization.objects.bootstrap(
                    self.user,
                    plugins_access_level=Organization.PluginsAccessLevel.INSTALL,
                )

        self.assertEqual(Plugin.objects.filter(organization=new_org, is_preinstalled=True).count(), 1)
        self.assertEqual(
            Plugin.objects.filter(organization=new_org, is_preinstalled=True).get().name,
            "helloworldplugin",
        )
        self.assertEqual(mock_get.call_count, 2)
        mock_get.assert_any_call(
            f"https://github.com/PostHog/helloworldplugin/archive/{HELLO_WORLD_PLUGIN_GITHUB_ZIP[0]}.zip",
            headers={},
        )

    @mock.patch("requests.get", side_effect=mocked_plugin_requests_get)
    def test_plugins_are_not_preinstalled_on_cloud(self, mock_get):
        with self.is_cloud(True):
            with self.settings(PLUGINS_PREINSTALLED_URLS=["https://github.com/PostHog/helloworldplugin/"]):
                new_org, _, _ = Organization.objects.bootstrap(
                    self.user,
                    plugins_access_level=Organization.PluginsAccessLevel.INSTALL,
                )

        self.assertEqual(Plugin.objects.filter(organization=new_org, is_preinstalled=True).count(), 0)
        self.assertEqual(mock_get.call_count, 0)

    def test_plugins_access_level_is_determined_based_on_realm(self):
        with self.is_cloud(True):
            new_org, _, _ = Organization.objects.bootstrap(self.user)
            assert new_org.plugins_access_level == Organization.PluginsAccessLevel.CONFIG

        with self.is_cloud(False):
            new_org, _, _ = Organization.objects.bootstrap(self.user)
            assert new_org.plugins_access_level == Organization.PluginsAccessLevel.ROOT

    def test_update_available_product_features_ignored_if_usage_info_exists(self):
        with self.is_cloud(False):
            new_org, _, _ = Organization.objects.bootstrap(self.user)

            new_org.available_product_features = [{"key": "test1", "name": "test1"}, {"key": "test2", "name": "test2"}]
            new_org.update_available_product_features()
            assert new_org.available_product_features == []

            new_org.available_product_features = [{"key": "test1", "name": "test1"}, {"key": "test2", "name": "test2"}]
            new_org.usage = {"events": {"usage": 1000, "limit": None}}
            new_org.update_available_product_features()
            assert new_org.available_product_features == [
                {"key": "test1", "name": "test1"},
                {"key": "test2", "name": "test2"},
            ]

    def test_session_age_caching(self):
        # Test caching when session_cookie_age is set
        self.organization.session_cookie_age = 3600
        self.organization.save()
        self.assertEqual(cache.get(f"org_session_age:{self.organization.id}"), 3600)

        # Test cache deletion when session_cookie_age is set to None
        self.organization.session_cookie_age = None
        self.organization.save()
        self.assertIsNone(cache.get(f"org_session_age:{self.organization.id}"))

        # Test cache update when session_cookie_age changes
        self.organization.session_cookie_age = 7200
        self.organization.save()
        self.assertEqual(cache.get(f"org_session_age:{self.organization.id}"), 7200)


class TestOrganizationMembership(BaseTest):
    @patch("posthoganalytics.capture")
    def test_event_sent_when_membership_level_changed(
        self,
        mock_capture,
    ):
        user = self._create_user("user1")
        organization = Organization.objects.create(name="Test Org")
        membership = OrganizationMembership.objects.create(user=user, organization=organization, level=1)
        mock_capture.assert_not_called()
        # change the level
        membership.level = 15
        membership.save()
        # check that the event was sent
        mock_capture.assert_called_once_with(
            event="membership level changed",
            distinct_id=user.distinct_id,
            properties={"new_level": 15, "previous_level": 1, "$set": mock.ANY},
            groups=mock.ANY,
        )
