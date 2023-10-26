import base64
import json
from datetime import datetime
from typing import Dict, List, cast
from unittest import mock
from unittest.mock import ANY, patch

from zoneinfo import ZoneInfo
from django.core.files.uploadedfile import SimpleUploadedFile
from freezegun import freeze_time
from rest_framework import status
from posthog.constants import FROZEN_POSTHOG_VERSION

from posthog.models import Plugin, PluginAttachment, PluginConfig, PluginSourceFile
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.plugins.access import (
    can_configure_plugins,
    can_globally_manage_plugins,
    can_install_plugins,
    can_view_plugins,
)
from posthog.plugins.test.mock import mocked_plugin_requests_get
from posthog.plugins.test.plugin_archives import (
    HELLO_WORLD_PLUGIN_GITHUB_ATTACHMENT_ZIP,
    HELLO_WORLD_PLUGIN_GITHUB_ZIP,
    HELLO_WORLD_PLUGIN_SECRET_GITHUB_ZIP,
)
from posthog.queries.app_metrics.test.test_app_metrics import create_app_metric
from posthog.test.base import APIBaseTest, QueryMatchingTest, snapshot_postgres_queries


def mocked_plugin_reload(*args, **kwargs):
    pass


@mock.patch("posthog.models.plugin.reload_plugins_on_workers", side_effect=mocked_plugin_reload)
@mock.patch("requests.get", side_effect=mocked_plugin_requests_get)
class TestPluginAPI(APIBaseTest, QueryMatchingTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # We make sure the org has permissions for these tests
        cls.organization.plugins_access_level = Organization.PluginsAccessLevel.ROOT
        cls.organization.save()

    def _get_plugin_activity(self, expected_status: int = status.HTTP_200_OK):
        activity = self.client.get(f"/api/organizations/@current/plugins/activity")
        self.assertEqual(activity.status_code, expected_status)
        return activity.json()

    def assert_plugin_activity(self, expected: List[Dict]):
        activity_response = self._get_plugin_activity()

        activity: List[Dict] = activity_response["results"]
        self.maxDiff = None
        self.assertEqual(activity, expected)

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_create_plugin_auth(self, mock_get, mock_reload):
        repo_url = "https://github.com/PostHog/helloworldplugin"

        for level in (
            Organization.PluginsAccessLevel.NONE,
            Organization.PluginsAccessLevel.CONFIG,
        ):
            self.organization.plugins_access_level = level
            self.organization.save()
            response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url})
            self.assertEqual(
                response.status_code,
                403,
                "Did not reject plugin installation as non-install org properly",
            )

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.INSTALL
        self.organization.save()
        response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url})
        self.assertEqual(
            response.status_code,
            201,
            "Did not manage to install plugin properly despite install access",
        )

        self.assert_plugin_activity(
            [
                {
                    "user": {"first_name": "", "email": "user1@posthog.com"},
                    "activity": "installed",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "Plugin",
                    "item_id": str(response.json()["id"]),
                    "detail": {
                        "name": "helloworldplugin",
                        "changes": None,
                        "trigger": None,
                        "type": None,
                        "short_id": None,
                    },
                }
            ]
        )

        response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url})
        self.assertEqual(
            response.status_code,
            400,
            "Did not reject already installed plugin properly",
        )

    def test_create_plugin_auth_globally_managed(self, mock_get, mock_reload):
        repo_url = "https://github.com/PostHog/helloworldplugin"

        for level in (
            Organization.PluginsAccessLevel.NONE,
            Organization.PluginsAccessLevel.CONFIG,
            Organization.PluginsAccessLevel.INSTALL,
        ):
            self.organization.plugins_access_level = level
            self.organization.save()
            response = self.client.post(
                "/api/organizations/@current/plugins/",
                {"url": repo_url, "is_global": True},
            )
            self.assertEqual(
                response.status_code,
                403,
                "Did not reject globally managed plugin installation as non-root org properly",
            )

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.ROOT
        self.organization.save()
        response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url, "is_global": True})
        self.assertEqual(
            response.status_code,
            201,
            "Did not manage to install globally managed plugin properly despite root access",
        )

        response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url, "is_global": True})
        self.assertEqual(
            response.status_code,
            400,
            "Did not reject already installed plugin properly",
        )

    def test_globally_managed_visible_to_all_orgs(self, mock_get, mock_reload):
        my_org = self.organization
        other_org: Organization = Organization.objects.create(
            name="FooBar2", plugins_access_level=Organization.PluginsAccessLevel.CONFIG
        )
        OrganizationMembership.objects.create(user=self.user, organization=other_org)

        repo_url = "https://github.com/PostHog/helloworldplugin"
        install_response = self.client.post(f"/api/organizations/{my_org.id}/plugins/", {"url": repo_url})
        self.assertEqual(
            install_response.status_code,
            201,
            "Did not manage to install plugin properly",
        )
        # The plugin is NOT global and should only show up for my org
        list_response_other_org_1 = self.client.get(f"/api/organizations/{other_org.id}/plugins/")
        self.assertDictEqual(
            list_response_other_org_1.json(),
            {"count": 0, "next": None, "previous": None, "results": []},
        )
        self.assertEqual(list_response_other_org_1.status_code, 200)
        # Let's make the plugin global
        update_response_my_org = self.client.patch(
            f"/api/organizations/{my_org.id}/plugins/{install_response.json()['id']}/",
            {"is_global": True},
        )
        self.assertEqual(update_response_my_org.status_code, 200)
        # Now the plugin is global and should show up for other org
        list_response_other_org_2 = self.client.get(f"/api/organizations/{other_org.id}/plugins/")
        list_response_other_org_2_data = list_response_other_org_2.json()
        self.assertEqual(list_response_other_org_2_data["count"], 1)
        self.assertEqual(list_response_other_org_2.status_code, 200)

    def test_no_longer_globally_managed_still_visible_to_org_iff_has_config(self, mock_get, mock_reload):
        other_org: Organization = Organization.objects.create(
            name="FooBar2", plugins_access_level=Organization.PluginsAccessLevel.CONFIG
        )
        no_plugins_org: Organization = Organization.objects.create(
            name="NoPlugins",
            plugins_access_level=Organization.PluginsAccessLevel.CONFIG,
        )
        other_team: Team = Team.objects.create(organization=other_org, name="FooBar2")
        OrganizationMembership.objects.create(user=self.user, organization=other_org)
        plugin = Plugin.objects.create(organization=self.organization)
        PluginConfig.objects.create(plugin=plugin, enabled=False, team=other_team, order=0)
        # The plugin is NOT global and it has a config for one of the projects,
        # so it should still show up for the other org
        list_response = self.client.get(f"/api/organizations/{other_org.id}/plugins/")
        self.assertEqual(list_response.status_code, 200, list_response.json())
        list_response_data = list_response.json()
        self.assertEqual(list_response_data["count"], 1)
        self.assertEqual(list_response_data["results"][0]["id"], plugin.id)
        # but org without any plugin configs won't have access
        list_response = self.client.get(f"/api/organizations/{no_plugins_org.id}/plugins/")
        self.assertEqual(list_response.status_code, 403, list_response.json())

    def test_globally_managed_only_manageable_by_owner_org(self, mock_get, mock_reload):
        my_org = self.organization
        other_org: Organization = Organization.objects.create(
            name="FooBar2", plugins_access_level=Organization.PluginsAccessLevel.ROOT
        )
        OrganizationMembership.objects.create(user=self.user, organization=other_org)

        repo_url = "https://github.com/PostHog/helloworldplugin"
        install_response = self.client.post(
            f"/api/organizations/{my_org.id}/plugins/",
            {"url": repo_url, "is_global": True},
        )
        self.assertEqual(
            install_response.status_code,
            201,
            "Did not manage to install globally managed plugin properly",
        )

        # My org
        patch_response_other_org_1 = self.client.patch(
            f"/api/organizations/{my_org.id}/plugins/{install_response.json()['id']}",
            {"description": "X"},
        )
        self.assertEqual(patch_response_other_org_1.status_code, 200)
        self.assertEqual("X", patch_response_other_org_1.json().get("description"))

        # Other org
        patch_response_other_org_2 = self.client.patch(
            f"/api/organizations/{other_org.id}/plugins/{install_response.json()['id']}",
            {"description": "Y"},
        )
        self.assertEqual(patch_response_other_org_2.status_code, 403)
        self.assertIn(
            "This plugin installation is managed by another organization",
            patch_response_other_org_2.json().get("detail"),
        )

    def test_update_plugin_auth_to_globally_managed(self, mock_get, mock_reload):
        repo_url = "https://github.com/PostHog/helloworldplugin"
        install_response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url})
        self.assertEqual(install_response.status_code, 201)

        for is_global in (True, False):
            for level in (
                Organization.PluginsAccessLevel.NONE,
                Organization.PluginsAccessLevel.CONFIG,
            ):
                self.organization.plugins_access_level = level
                self.organization.save()
                response = self.client.patch(
                    f"/api/organizations/@current/plugins/{install_response.json()['id']}/",
                    {"is_global": is_global},
                )
                self.assertEqual(
                    response.status_code,
                    403,
                    "Plugin was not 403 for org despite it having no plugin install access",
                )

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.INSTALL
        self.organization.save()
        for is_global in (True, False):
            response = self.client.patch(
                f"/api/organizations/@current/plugins/{install_response.json()['id']}/",
                {"is_global": is_global},
            )
            self.assertEqual(
                response.status_code,
                403,
                "Did not reject globally managed plugin update as non-root org properly",
            )

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.ROOT
        self.organization.save()
        for is_global in (True, False):
            response = self.client.patch(
                f"/api/organizations/@current/plugins/{install_response.json()['id']}/",
                {"is_global": is_global},
            )
            self.assertEqual(
                response.status_code,
                200,
                "Did not manage to make plugin globally managed properly despite root access",
            )

    def test_plugin_private_token_url_unique(self, mock_get, mock_reload):
        repo_url = "https://gitlab.com/mariusandra/helloworldplugin"
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"url": f"{repo_url}?private_token=123"},
        )
        self.assertEqual(response.status_code, 201)
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"url": f"{repo_url}?private_token=123"},
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url})
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"url": f"{repo_url}?private_token=567"},
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post("/api/organizations/@current/plugins/", {"url": f"{repo_url}-other"})
        self.assertEqual(response.status_code, 201)
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"url": f"{repo_url}-other?private_token=567"},
        )
        self.assertEqual(response.status_code, 400)

    @mock.patch("posthog.models.plugin.PluginSourceFile.objects.sync_from_plugin_archive")
    def test_update_plugin_auth(self, mock_sync_from_plugin_archive, mock_get, mock_reload):
        self.assertEqual(mock_reload.call_count, 0)
        self.assertEqual(mock_sync_from_plugin_archive.call_count, 0)
        repo_url = "https://github.com/PostHog/helloworldplugin"
        response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(mock_sync_from_plugin_archive.call_count, 1)  # Source files are extracted

        plugin = Plugin.objects.get(id=response.json()["id"])

        fake_date = datetime(2022, 1, 1, 0, 0).replace(tzinfo=ZoneInfo("UTC"))
        self.assertNotEqual(plugin.updated_at, fake_date)

        with freeze_time(fake_date.isoformat()):
            api_url = f"/api/organizations/@current/plugins/{response.json()['id']}/upgrade"
            response = self.client.post(api_url, {"url": repo_url})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(mock_sync_from_plugin_archive.call_count, 2)  # Source files are extracted
            plugin.refresh_from_db()
            self.assertEqual(plugin.updated_at, fake_date)

        for level in (
            Organization.PluginsAccessLevel.NONE,
            Organization.PluginsAccessLevel.CONFIG,
        ):
            self.organization.plugins_access_level = level
            self.organization.save()
            response = self.client.post(api_url, {"url": repo_url})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(mock_sync_from_plugin_archive.call_count, 2)  # Not extracted on auth failure

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_delete_plugin_auth(self, mock_get, mock_reload):
        repo_url = "https://github.com/PostHog/helloworldplugin"
        response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url})
        self.assertEqual(response.status_code, 201)

        plugin_id = response.json()["id"]

        api_url = "/api/organizations/@current/plugins/{}".format(response.json()["id"])

        for level in (
            Organization.PluginsAccessLevel.NONE,
            Organization.PluginsAccessLevel.CONFIG,
        ):
            self.organization.plugins_access_level = level
            self.organization.save()
            response = self.client.delete(api_url)
            self.assertEqual(response.status_code, 403)

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.INSTALL
        self.organization.save()
        response = self.client.delete(api_url)
        self.assertEqual(response.status_code, 204)
        self.assert_plugin_activity(
            [
                {
                    "user": {"first_name": "", "email": "user1@posthog.com"},
                    "activity": "installed",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "Plugin",
                    "item_id": str(plugin_id),
                    "detail": {
                        "name": "helloworldplugin",
                        "changes": None,
                        "trigger": None,
                        "type": None,
                        "short_id": None,
                    },
                },
                {
                    "user": {"first_name": "", "email": "user1@posthog.com"},
                    "activity": "uninstalled",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "Plugin",
                    "item_id": str(plugin_id),
                    "detail": {
                        "name": "helloworldplugin",
                        "changes": None,
                        "trigger": None,
                        "type": None,
                        "short_id": None,
                    },
                },
            ]
        )

    def test_cannot_delete_of_other_orgs_plugin(self, mock_get, mock_reload):
        other_org = Organization.objects.create(
            name="FooBar2", plugins_access_level=Organization.PluginsAccessLevel.INSTALL
        )
        OrganizationMembership.objects.create(organization=other_org, user=self.user)

        repo_url = "https://github.com/PostHog/helloworldplugin"
        response = self.client.post(f"/api/organizations/@current/plugins/", {"url": repo_url})

        self.assertEqual(response.status_code, 201)

        self.user.current_organization = other_org
        self.user.save()

        api_url = f"/api/organizations/@current/plugins/{response.json()['id']}"
        response = self.client.delete(api_url)

        self.assertEqual(response.status_code, 404)

    def test_cannot_delete_global_plugin(self, mock_get, mock_reload):
        repo_url = "https://github.com/PostHog/helloworldplugin"
        response = self.client.post(
            f"/api/organizations/@current/plugins/",
            {"url": repo_url, "is_global": True},
        )

        self.assertEqual(response.status_code, 201)

        api_url = f"/api/organizations/@current/plugins/{response.json()['id']}"
        response = self.client.delete(api_url)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json().get("detail"),
            "This plugin is marked as global! Make it local before uninstallation",
        )

    def test_create_plugin_repo_url(self, mock_get, mock_reload):
        self.assertEqual(mock_reload.call_count, 0)
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"url": "https://github.com/PostHog/helloworldplugin"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json(),
            {
                "id": response.json()["id"],
                "plugin_type": "custom",
                "name": "helloworldplugin",
                "description": "Greet the World and Foo a Bar, JS edition!",
                "url": "https://github.com/PostHog/helloworldplugin",
                "icon": None,
                "config_schema": {
                    "bar": {
                        "name": "What's in the bar?",
                        "type": "string",
                        "default": "baz",
                        "required": False,
                    }
                },
                "tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                "latest_tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                "is_global": False,
                "organization_id": response.json()["organization_id"],
                "organization_name": self.CONFIG_ORGANIZATION_NAME,
                "capabilities": {},
                "metrics": {},
                "public_jobs": {},
            },
        )
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginSourceFile.objects.filter(filename="plugin.json").count(), 1)
        self.assertEqual(PluginSourceFile.objects.filter(filename="index.ts").count(), 1)
        self.assertEqual(mock_reload.call_count, 1)

        self.client.delete("/api/organizations/@current/plugins/{}".format(response.json()["id"]))
        self.assertEqual(Plugin.objects.count(), 0)
        self.assertEqual(PluginSourceFile.objects.count(), 0)
        self.assertEqual(mock_reload.call_count, 2)

    def test_create_plugin_commit_url(self, mock_get, mock_reload):
        self.assertEqual(mock_reload.call_count, 0)
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"url": f"https://github.com/PostHog/helloworldplugin/commit/{HELLO_WORLD_PLUGIN_GITHUB_ZIP[0]}"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json(),
            {
                "id": response.json()["id"],
                "plugin_type": "custom",
                "name": "helloworldplugin",
                "description": "Greet the World and Foo a Bar, JS edition!",
                "url": f"https://github.com/PostHog/helloworldplugin/commit/{HELLO_WORLD_PLUGIN_GITHUB_ZIP[0]}",
                "icon": None,
                "config_schema": {
                    "bar": {
                        "name": "What's in the bar?",
                        "type": "string",
                        "default": "baz",
                        "required": False,
                    }
                },
                "tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                "latest_tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                "is_global": False,
                "organization_id": response.json()["organization_id"],
                "organization_name": self.CONFIG_ORGANIZATION_NAME,
                "capabilities": {},
                "metrics": {},
                "public_jobs": {},
            },
        )
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(mock_reload.call_count, 1)

    def test_create_plugin_other_commit_url(self, mock_get, mock_reload):
        self.assertEqual(mock_reload.call_count, 0)
        response2 = self.client.post(
            "/api/organizations/@current/plugins/",
            {
                "url": "https://github.com/PostHog/helloworldplugin/commit/{}".format(
                    HELLO_WORLD_PLUGIN_GITHUB_ATTACHMENT_ZIP[0]
                )
            },
        )
        self.assertEqual(response2.status_code, 201)
        self.assertEqual(
            response2.json(),
            {
                "id": response2.json()["id"],
                "plugin_type": "custom",
                "name": "helloworldplugin",
                "description": "Greet the World and Foo a Bar, JS edition, vol 2!",
                "url": f"https://github.com/PostHog/helloworldplugin/commit/{HELLO_WORLD_PLUGIN_GITHUB_ATTACHMENT_ZIP[0]}",
                "icon": None,
                "config_schema": {
                    "bar": {
                        "name": "What's in the bar?",
                        "type": "string",
                        "default": "baz",
                        "required": False,
                    },
                    "foodb": {
                        "name": "Upload your database",
                        "type": "attachment",
                        "required": False,
                    },
                },
                "tag": HELLO_WORLD_PLUGIN_GITHUB_ATTACHMENT_ZIP[0],
                "latest_tag": HELLO_WORLD_PLUGIN_GITHUB_ATTACHMENT_ZIP[0],
                "is_global": False,
                "organization_id": response2.json()["organization_id"],
                "organization_name": self.CONFIG_ORGANIZATION_NAME,
                "capabilities": {},
                "metrics": {},
                "public_jobs": {},
            },
        )
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(mock_reload.call_count, 1)

    def test_create_plugin_version_range_eq_current(self, mock_get, mock_reload):
        with self.is_cloud(False):
            response = self.client.post(
                "/api/organizations/@current/plugins/",
                {"url": f"https://github.com/posthog-plugin/version-equals/commit/{FROZEN_POSTHOG_VERSION}"},
            )
            self.assertEqual(response.status_code, 201)

    def test_create_plugin_version_range_eq_next_minor(self, mock_get, mock_reload):
        with self.is_cloud(False):
            response = self.client.post(
                "/api/organizations/@current/plugins/",
                {
                    "url": f"https://github.com/posthog-plugin/version-equals/commit/{FROZEN_POSTHOG_VERSION.next_minor()}"
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                cast(Dict[str, str], response.json())["detail"],
                f'Currently running PostHog version {FROZEN_POSTHOG_VERSION} does not match this plugin\'s semantic version requirement "{FROZEN_POSTHOG_VERSION.next_minor()}".',
            )

    def test_create_plugin_version_range_gt_current(self, mock_get, mock_reload):
        with self.is_cloud(False):
            response = self.client.post(
                "/api/organizations/@current/plugins/",
                {"url": f"https://github.com/posthog-plugin/version-greater-than/commit/0.0.0"},
            )
            self.assertEqual(response.status_code, 201)

    def test_create_plugin_version_range_gt_next_major(self, mock_get, mock_reload):
        with self.is_cloud(False):
            response = self.client.post(
                "/api/organizations/@current/plugins/",
                {
                    "url": f"https://github.com/posthog-plugin/version-greater-than/commit/{FROZEN_POSTHOG_VERSION.next_major()}"
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                cast(Dict[str, str], response.json())["detail"],
                f'Currently running PostHog version {FROZEN_POSTHOG_VERSION} does not match this plugin\'s semantic version requirement ">= {FROZEN_POSTHOG_VERSION.next_major()}".',
            )

    def test_create_plugin_version_range_lt_current(self, mock_get, mock_reload):
        with self.is_cloud(False):
            response = self.client.post(
                "/api/organizations/@current/plugins/",
                {"url": f"https://github.com/posthog-plugin/version-less-than/commit/{FROZEN_POSTHOG_VERSION}"},
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                cast(Dict[str, str], response.json())["detail"],
                f'Currently running PostHog version {FROZEN_POSTHOG_VERSION} does not match this plugin\'s semantic version requirement "< {FROZEN_POSTHOG_VERSION}".',
            )

    def test_create_plugin_version_range_lt_next_major(self, mock_get, mock_reload):
        with self.is_cloud(False):
            response = self.client.post(
                "/api/organizations/@current/plugins/",
                {
                    "url": f"https://github.com/posthog-plugin/version-less-than/commit/{FROZEN_POSTHOG_VERSION.next_major()}"
                },
            )
            self.assertEqual(response.status_code, 201)

    def test_create_plugin_version_range_lt_invalid(self, mock_get, mock_reload):
        with self.is_cloud(False):
            response = self.client.post(
                "/api/organizations/@current/plugins/",
                {"url": f"https://github.com/posthog-plugin/version-less-than/commit/..."},
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                cast(Dict[str, str], response.json())["detail"],
                'Invalid PostHog semantic version requirement "< ..."!',
            )

    def test_create_plugin_version_range_gt_next_major_ignore_on_cloud(self, mock_get, mock_reload):
        with self.is_cloud(True):
            response = self.client.post(
                "/api/organizations/@current/plugins/",
                {
                    "url": f"https://github.com/posthog-plugin/version-greater-than/commit/{FROZEN_POSTHOG_VERSION.next_major()}"
                },
            )
            self.assertEqual(response.status_code, 201)

    def test_update_plugin_source(self, mock_get, mock_reload):
        # Create the plugin
        self.assertEqual(mock_reload.call_count, 0)
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"plugin_type": "source", "name": "myplugin_original"},
        )
        plugin_id = response.json()["id"]
        self.assertEqual(mock_reload.call_count, 0)

        # There is no actual source code stored yet
        response = self.client.get(f"/api/organizations/@current/plugins/{plugin_id}/source")
        self.assertEqual(response.json(), {})
        self.assertEqual(Plugin.objects.get(pk=plugin_id).name, "myplugin_original")

        # Create two files: index.ts and plugin.json
        response = self.client.patch(
            f"/api/organizations/@current/plugins/{plugin_id}/update_source",
            data=json.dumps({"index.ts": "'hello world'", "plugin.json": '{"name":"my plugin"}'}),
            content_type="application/json",
        )
        self.assertEqual(
            response.json(),
            {"index.ts": "'hello world'", "plugin.json": '{"name":"my plugin"}'},
        )
        self.assertEqual(Plugin.objects.get(pk=plugin_id).name, "my plugin")
        self.assertEqual(mock_reload.call_count, 1)

        # Modifying just one file will not alter the other
        response = self.client.patch(
            f"/api/organizations/@current/plugins/{plugin_id}/update_source",
            data=json.dumps({"index.ts": "'hello again'"}),
            content_type="application/json",
        )
        self.assertEqual(
            response.json(),
            {"index.ts": "'hello again'", "plugin.json": '{"name":"my plugin"}'},
        )
        self.assertEqual(mock_reload.call_count, 2)

        # Deleting a file by passing `None`
        response = self.client.patch(
            f"/api/organizations/@current/plugins/{plugin_id}/update_source",
            data=json.dumps({"index.ts": None}),
            content_type="application/json",
        )
        self.assertEqual(response.json(), {"plugin.json": '{"name":"my plugin"}'})
        self.assertEqual(mock_reload.call_count, 3)

    def test_create_plugin_frontend_source(self, mock_get, mock_reload):
        self.assertEqual(mock_reload.call_count, 0)
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"plugin_type": "source", "name": "myplugin"},
        )
        self.assertEqual(response.status_code, 201)
        id = response.json()["id"]
        self.assertEqual(
            response.json(),
            {
                "id": id,
                "plugin_type": "source",
                "name": "myplugin",
                "description": None,
                "url": None,
                "config_schema": {},
                "tag": None,
                "icon": None,
                "latest_tag": None,
                "is_global": False,
                "organization_id": response.json()["organization_id"],
                "organization_name": self.CONFIG_ORGANIZATION_NAME,
                "capabilities": {},
                "metrics": {},
                "public_jobs": {},
            },
        )
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(mock_reload.call_count, 0)

        response = self.client.patch(
            f"/api/organizations/@current/plugins/{id}/update_source",
            {"frontend.tsx": "export const scene = {}"},
        )

        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginSourceFile.objects.count(), 1)
        self.assertEqual(mock_reload.call_count, 1)

        plugin = Plugin.objects.get(pk=id)
        plugin_config = PluginConfig.objects.create(plugin=plugin, team=self.team, enabled=True, order=1)

        # no frontend, since no pluginserver transpiles the code
        response = self.client.get(f"/api/plugin_config/{plugin_config.id}/frontend")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.content,
            b'export function getFrontendApp () { return {"transpiling": true} }',
        )

        # mock the plugin server's transpilation
        plugin_source = PluginSourceFile.objects.get(plugin_id=id)
        self.assertEqual(plugin_source.status, None)
        self.assertEqual(plugin_source.transpiled, None)
        plugin_source.status = PluginSourceFile.Status.TRANSPILED
        plugin_source.transpiled = "'random transpiled frontend'"
        plugin_source.save()

        # Can get the transpiled frontend
        response = self.client.get(f"/api/plugin_config/{plugin_config.id}/frontend")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"'random transpiled frontend'")

        # Update the source frontend
        self.client.patch(
            f"/api/organizations/@current/plugins/{id}/update_source",
            {"frontend.tsx": "export const scene = { name: 'new' }"},
        )

        # It will clear the transpiled frontend
        plugin_source = PluginSourceFile.objects.get(plugin_id=id)
        self.assertEqual(plugin_source.source, "export const scene = { name: 'new' }")
        self.assertEqual(plugin_source.transpiled, None)

        # And reply that it's transpiling
        response = self.client.get(f"/api/plugin_config/{plugin_config.id}/frontend")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.content,
            b'export function getFrontendApp () { return {"transpiling": true} }',
        )

    def test_plugin_repository(self, mock_get, mock_reload):
        response = self.client.get("/api/organizations/@current/plugins/repository/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {
                    "name": "posthog-currency-normalization-plugin",
                    "url": "https://github.com/posthog/posthog-currency-normalization-plugin",
                    "description": "Normalise monerary values into a base currency",
                    "icon": "https://raw.githubusercontent.com/posthog/posthog-currency-normalization-plugin/main/logo.png",
                    "verified": False,
                    "maintainer": "official",
                },
                {
                    "name": "helloworldplugin",
                    "url": "https://github.com/posthog/helloworldplugin",
                    "description": "Greet the World and Foo a Bar",
                    "icon": "https://raw.githubusercontent.com/posthog/helloworldplugin/main/logo.png",
                    "verified": True,
                    "maintainer": "community",
                },
            ],
        )

    def test_plugin_unused(self, mock_get, mock_reload):
        plugin_no_configs = Plugin.objects.create(organization=self.organization)
        plugin_enabled = Plugin.objects.create(organization=self.organization)
        plugin_only_disabled = Plugin.objects.create(organization=self.organization)
        PluginConfig.objects.create(plugin=plugin_only_disabled, team=self.team, enabled=False, order=1)
        PluginConfig.objects.create(plugin=plugin_enabled, team=self.team, enabled=False, order=1)
        PluginConfig.objects.create(plugin=plugin_enabled, team=self.team, enabled=True, order=2)
        response = self.client.get("/api/organizations/@current/plugins/unused/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [plugin_no_configs.id, plugin_only_disabled.id],
        )

    def test_install_plugin_on_multiple_orgs(self, mock_get, mock_reload):
        my_org = self.organization
        other_org = Organization.objects.create(
            name="FooBar2", plugins_access_level=Organization.PluginsAccessLevel.INSTALL
        )

        fake_date = datetime(2022, 1, 1, 0, 0).replace(tzinfo=ZoneInfo("UTC"))
        with freeze_time(fake_date.isoformat()):
            response = self.client.post(
                f"/api/organizations/{my_org.id}/plugins/",
                {"url": "https://github.com/PostHog/helloworldplugin"},
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(Plugin.objects.count(), 1)

            plugin = Plugin.objects.all()[0]
            self.assertEqual(plugin.updated_at, fake_date)

        response = self.client.post(
            f"/api/organizations/{my_org.id}/plugins/",
            {"url": "https://github.com/PostHog/helloworldplugin"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Plugin.objects.count(), 1)

        # try to save it for another org
        response = self.client.post(
            f"/api/organizations/{other_org.id}/plugins/",
            {"url": "https://github.com/PostHog/helloworldplugin"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Plugin.objects.count(), 1)

        self.user.join(organization=other_org, level=OrganizationMembership.Level.OWNER)

        response = self.client.post(
            f"/api/organizations/{other_org.id}/plugins/",
            {"url": "https://github.com/PostHog/helloworldplugin"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Plugin.objects.count(), 2)
        response = self.client.post(
            f"/api/organizations/{other_org.id}/plugins/",
            {"url": "https://github.com/PostHog/helloworldplugin"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Plugin.objects.count(), 2)

    def test_cannot_access_others_orgs_plugins(self, mock_get, mock_reload):
        other_org = Organization.objects.create(
            name="Foo", plugins_access_level=Organization.PluginsAccessLevel.INSTALL
        )
        other_orgs_plugin = Plugin.objects.create(organization=other_org)
        this_orgs_plugin = Plugin.objects.create(organization=self.organization)
        response_other = self.client.get(f"/api/organizations/@current/plugins/{other_orgs_plugin.id}/")
        self.assertEqual(response_other.status_code, 404)
        response_this = self.client.get(f"/api/organizations/@current/plugins/{this_orgs_plugin.id}/")
        self.assertEqual(response_this.status_code, 200)

    @snapshot_postgres_queries
    def test_listing_plugins_is_not_nplus1(self, _mock_get, _mock_reload) -> None:
        with self.assertNumQueries(7):
            self._assert_number_of_when_listed_plugins(0)

        Plugin.objects.create(organization=self.organization)

        with self.assertNumQueries(7):
            self._assert_number_of_when_listed_plugins(1)

        Plugin.objects.create(organization=self.organization)

        with self.assertNumQueries(7):
            self._assert_number_of_when_listed_plugins(2)

        Plugin.objects.create(organization=self.organization)

        with self.assertNumQueries(7):
            self._assert_number_of_when_listed_plugins(3)

    def _assert_number_of_when_listed_plugins(self, expected_plugins_count: int) -> None:
        response_with_none = self.client.get(f"/api/organizations/@current/plugins/")
        self.assertEqual(response_with_none.status_code, 200)
        self.assertEqual(
            response_with_none.json()["count"],
            expected_plugins_count,
            response_with_none.json(),
        )
        self.assertEqual(
            len(response_with_none.json()["results"]),
            expected_plugins_count,
            response_with_none.json(),
        )

    def test_create_plugin_config(self, mock_get, mock_reload):
        self.assertEqual(mock_reload.call_count, 0)
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"url": "https://github.com/PostHog/helloworldplugin"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginConfig.objects.count(), 0)
        plugin_id = response.json()["id"]
        response = self.client.post(
            "/api/plugin_config/",
            {
                "plugin": plugin_id,
                "enabled": True,
                "order": 0,
                "config": json.dumps({"bar": "moop"}),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.content)
        plugin_config_id = response.json()["id"]
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginConfig.objects.count(), 1)
        self.assertEqual(
            response.json(),
            {
                "id": plugin_config_id,
                "plugin": plugin_id,
                "enabled": True,
                "order": 0,
                "config": {"bar": "moop"},
                "error": None,
                "team_id": self.team.pk,
                "plugin_info": None,
                "delivery_rate_24h": None,
                "created_at": mock.ANY,
            },
        )
        plugin_config = PluginConfig.objects.first()
        self.assertIsNotNone(plugin_config.web_token)  # type: ignore

        # If we're trying to create another plugin config for the same plugin, just return the original
        response = self.client.post(
            "/api/plugin_config/",
            {
                "plugin": plugin_id,
                "enabled": True,
                "order": 0,
                "config": json.dumps({"bar": "moop"}),
            },
            format="multipart",
        )
        self.assertEqual(response.json()["id"], plugin_config_id)

        response = self.client.patch(
            f"/api/plugin_config/{plugin_config_id}",
            {"enabled": False, "order": 1, "config": json.dumps({"bar": "soup"})},
            format="multipart",
        )
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginConfig.objects.count(), 1)
        self.assertEqual(
            response.json(),
            {
                "id": plugin_config_id,
                "plugin": plugin_id,
                "enabled": False,
                "order": 1,
                "config": {"bar": "soup"},
                "error": None,
                "team_id": self.team.pk,
                "plugin_info": None,
                "delivery_rate_24h": None,
                "created_at": mock.ANY,
            },
        )
        self.client.delete(f"/api/plugin_config/{plugin_config_id}")
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginConfig.objects.count(), 1)

    def test_create_plugin_config_auth(self, mock_get, mock_reload):
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"url": "https://github.com/PostHog/helloworldplugin"},
        )
        plugin_id = response.json()["id"]

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.NONE
        self.organization.save()
        response = self.client.post(
            "/api/plugin_config/",
            {
                "plugin": plugin_id,
                "enabled": True,
                "order": 0,
                "config": json.dumps({"bar": "moop"}),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)

        for level in (
            Organization.PluginsAccessLevel.ROOT,
            Organization.PluginsAccessLevel.INSTALL,
            Organization.PluginsAccessLevel.CONFIG,
        ):
            self.organization.plugins_access_level = level
            self.organization.save()
            response = self.client.post(
                "/api/plugin_config/",
                {
                    "plugin": plugin_id,
                    "enabled": True,
                    "order": 0,
                    "config": json.dumps({"bar": "moop"}),
                },
                format="multipart",
            )
            self.assertEqual(response.status_code, 201)

    def test_update_plugin_config_auth(self, mock_get, mock_reload):
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"url": "https://github.com/PostHog/helloworldplugin"},
        )
        plugin_id = response.json()["id"]
        response = self.client.post(
            "/api/plugin_config/",
            {
                "plugin": plugin_id,
                "enabled": True,
                "order": 0,
                "config": json.dumps({"bar": "moop"}),
            },
            format="multipart",
        )
        plugin_config_id = response.json()["id"]

        for level in (
            Organization.PluginsAccessLevel.ROOT,
            Organization.PluginsAccessLevel.INSTALL,
            Organization.PluginsAccessLevel.CONFIG,
        ):
            self.organization.plugins_access_level = level
            self.organization.save()
            response = self.client.patch(
                f"/api/plugin_config/{plugin_config_id}",
                {"enabled": False, "order": 1, "config": json.dumps({"bar": "soup"})},
                format="multipart",
            )
            self.assertEqual(response.status_code, 200)

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.NONE
        self.organization.save()
        response = self.client.patch(
            f"/api/plugin_config/{plugin_config_id}",
            {"enabled": False, "order": 1, "config": json.dumps({"bar": "soup"})},
            format="multipart",
        )
        self.assertEqual(response.status_code, 404)

    def test_update_plugin_config_no_longer_globally_managed_but_still_enabled(self, mock_get, mock_reload):
        self.organization.plugins_access_level = Organization.PluginsAccessLevel.CONFIG
        self.organization.save()
        other_org: Organization = Organization.objects.create(
            name="FooBar2", plugins_access_level=Organization.PluginsAccessLevel.CONFIG
        )
        other_team: Team = Team.objects.create(organization=other_org, name="FooBar2")
        OrganizationMembership.objects.create(user=self.user, organization=other_org)
        plugin = Plugin.objects.create(organization=self.organization)
        plugin_config = PluginConfig.objects.create(plugin=plugin, enabled=True, team=other_team, order=0)
        # The plugin is NOT global BUT it was before and it was enabled for the project back then,
        # so it should still be editable for the other org
        response = self.client.patch(
            f"/api/projects/{other_team.pk}/plugin_configs/{plugin_config.pk}/",
            {"order": 2},
            format="multipart",
        )
        self.assertEqual(response.status_code, 200)

    def test_delete_plugin_config_auth(self, mock_get, mock_reload):
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"url": "https://github.com/PostHog/helloworldplugin"},
        )
        plugin_id = response.json()["id"]
        response = self.client.post(
            "/api/plugin_config/",
            {
                "plugin": plugin_id,
                "enabled": True,
                "order": 0,
                "config": json.dumps({"bar": "moop"}),
            },
            format="multipart",
        )
        plugin_config_id = response.json()["id"]

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.NONE
        self.organization.save()
        response = self.client.delete(f"/api/plugin_config/{plugin_config_id}")
        self.assertEqual(response.status_code, 404)

        for level in (
            Organization.PluginsAccessLevel.ROOT,
            Organization.PluginsAccessLevel.INSTALL,
            Organization.PluginsAccessLevel.CONFIG,
        ):
            self.organization.plugins_access_level = level
            self.organization.save()
            response = self.client.delete(f"/api/plugin_config/{plugin_config_id}")
            self.assertEqual(response.status_code, 204)

    def test_plugin_config_attachment(self, mock_get, mock_reload):
        tmp_file_1 = SimpleUploadedFile(
            "foo-database-1.db",
            base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]),
            content_type="application/octet-stream",
        )
        tmp_file_2 = SimpleUploadedFile(
            "foo-database-2.db",
            base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ATTACHMENT_ZIP[1]),
            content_type="application/zip",
        )

        self.assertEqual(PluginAttachment.objects.count(), 0)
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {
                "url": "https://github.com/PostHog/helloworldplugin/commit/{}".format(
                    HELLO_WORLD_PLUGIN_GITHUB_ATTACHMENT_ZIP[0]
                )
            },
            format="multipart",
        )
        plugin_id = response.json()["id"]
        response = self.client.post(
            "/api/plugin_config/",
            {
                "plugin": plugin_id,
                "enabled": True,
                "order": 0,
                "config": json.dumps({"bar": "moop"}),
                "add_attachment[foodb]": tmp_file_1,
            },
            format="multipart",
        )
        plugin_config_id = response.json()["id"]
        plugin_attachment_id = response.json()["config"]["foodb"]["uid"]

        response = self.client.get(f"/api/plugin_config/{plugin_config_id}")
        self.assertEqual(
            response.json()["config"],
            {
                "bar": "moop",
                "foodb": {
                    "uid": plugin_attachment_id,
                    "saved": True,
                    "size": 1964,
                    "name": "foo-database-1.db",
                    "type": "application/octet-stream",
                },
            },
        )

        response = self.client.patch(
            f"/api/plugin_config/{plugin_config_id}",
            {"add_attachment[foodb]": tmp_file_2},
            format="multipart",
        )
        self.assertEqual(PluginAttachment.objects.count(), 1)

        self.assertEqual(
            response.json()["config"],
            {
                "bar": "moop",
                "foodb": {
                    "uid": plugin_attachment_id,
                    "saved": True,
                    "size": 2279,
                    "name": "foo-database-2.db",
                    "type": "application/zip",
                },
            },
        )

        response = self.client.patch(
            f"/api/plugin_config/{plugin_config_id}",
            {"remove_attachment[foodb]": True},
            format="multipart",
        )
        self.assertEqual(response.json()["config"], {"bar": "moop"})
        self.assertEqual(PluginAttachment.objects.count(), 0)

        response = self.client.get("/api/organizations/@current/plugins/activity")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        changes = response.json()["results"]

        self.assertEqual(len(changes), 5)

        for i in (0, 1, 2, 3):
            self.assertEqual(changes[i]["scope"], "PluginConfig")

        self.assertEqual(changes[4]["scope"], "Plugin")

        self.assertEqual(changes[0]["activity"], "attachment_deleted")
        self.assertEqual(
            changes[0]["detail"]["changes"],
            [
                {
                    "type": "PluginConfig",
                    "action": "deleted",
                    "field": None,
                    "before": "foo-database-2.db",
                    "after": None,
                }
            ],
        )

        self.assertEqual(changes[1]["activity"], "attachment_updated")
        self.assertEqual(
            changes[1]["detail"]["changes"],
            [
                {
                    "type": "PluginConfig",
                    "action": "changed",
                    "field": None,
                    "before": "foo-database-1.db",
                    "after": "foo-database-2.db",
                }
            ],
        )

        self.assertEqual(changes[2]["activity"], "attachment_created")
        self.assertEqual(
            changes[2]["detail"]["changes"],
            [
                {
                    "type": "PluginConfig",
                    "action": "created",
                    "field": None,
                    "before": None,
                    "after": "foo-database-1.db",
                }
            ],
        )

    def test_create_plugin_config_with_secrets(self, mock_get, mock_reload):
        self.assertEqual(mock_reload.call_count, 0)

        # Test that config can be created and secret value isn't exposed
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {
                "url": "https://github.com/PostHog/helloworldplugin/commit/{}".format(
                    HELLO_WORLD_PLUGIN_SECRET_GITHUB_ZIP[0]
                )
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginConfig.objects.count(), 0)
        plugin_id = response.json()["id"]
        response = self.client.post(
            "/api/plugin_config/",
            {
                "plugin": plugin_id,
                "enabled": True,
                "order": 0,
                "config": json.dumps({"bar": "very secret value"}),
            },
            format="multipart",
        )
        plugin_config_id = response.json()["id"]
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginConfig.objects.count(), 1)

        self.assertEqual(
            response.json(),
            {
                "id": plugin_config_id,
                "plugin": plugin_id,
                "enabled": True,
                "order": 0,
                "config": {"bar": "**************** POSTHOG SECRET FIELD ****************"},
                "error": None,
                "team_id": self.team.pk,
                "plugin_info": None,
                "delivery_rate_24h": None,
                "created_at": mock.ANY,
            },
        )

        # Test a config change and that an empty config is returned to the client instead of the secret placeholder
        response = self.client.patch(
            f"/api/plugin_config/{plugin_config_id}",
            {"enabled": False, "order": 1, "config": json.dumps({"bar": ""})},
            format="multipart",
        )
        plugin_config_id = response.json()["id"]
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginConfig.objects.count(), 1)
        self.assertEqual(
            response.json(),
            {
                "id": plugin_config_id,
                "plugin": plugin_id,
                "enabled": False,
                "order": 1,
                "config": {"bar": ""},  # empty secret configs are returned normally
                "error": None,
                "team_id": self.team.pk,
                "plugin_info": None,
                "delivery_rate_24h": None,
                "created_at": mock.ANY,
            },
        )

        # Test that secret values are updated but never revealed
        response = self.client.patch(
            f"/api/plugin_config/{plugin_config_id}",
            {
                "enabled": False,
                "order": 1,
                "config": json.dumps({"bar": "a new very secret value"}),
            },
            format="multipart",
        )
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(
            response.json(),
            {
                "id": plugin_config_id,
                "plugin": plugin_id,
                "enabled": False,
                "order": 1,
                "config": {"bar": "**************** POSTHOG SECRET FIELD ****************"},
                "error": None,
                "team_id": self.team.pk,
                "plugin_info": None,
                "delivery_rate_24h": None,
                "created_at": mock.ANY,
            },
        )
        plugin_config = PluginConfig.objects.get(plugin=plugin_id)
        self.assertEqual(plugin_config.config, {"bar": "a new very secret value"})

    @freeze_time("2021-12-05T13:23:00Z")
    def test_plugin_config_list(self, mock_get, mock_reload):
        plugin = Plugin.objects.create(organization=self.organization)
        plugin_config1 = PluginConfig.objects.create(plugin=plugin, team=self.team, enabled=True, order=1)
        plugin_config2 = PluginConfig.objects.create(plugin=plugin, team=self.team, enabled=True, order=2)

        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=plugin_config1.pk,
            timestamp="2021-12-05T00:10:00Z",
            successes=5,
            failures=5,
        )

        response = self.client.get("/api/plugin_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["results"],
            [
                {
                    "id": plugin_config1.pk,
                    "plugin": plugin.pk,
                    "enabled": True,
                    "order": 1,
                    "config": {},
                    "error": None,
                    "team_id": self.team.pk,
                    "plugin_info": None,
                    "delivery_rate_24h": 0.5,
                    "created_at": mock.ANY,
                },
                {
                    "id": plugin_config2.pk,
                    "plugin": plugin.pk,
                    "enabled": True,
                    "order": 2,
                    "config": {},
                    "error": None,
                    "team_id": self.team.pk,
                    "plugin_info": None,
                    "delivery_rate_24h": None,
                    "created_at": mock.ANY,
                },
            ],
        )

    @patch("posthog.api.plugin.validate_plugin_job_payload")
    @patch("posthog.api.plugin.connections")
    def test_job_trigger(self, db_connections, mock_validate_plugin_job_payload, mock_get, mock_reload):
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"url": "https://github.com/PostHog/helloworldplugin"},
        )
        plugin_id = response.json()["id"]
        response = self.client.post(
            "/api/plugin_config/",
            {
                "plugin": plugin_id,
                "enabled": True,
                "order": 0,
                "config": json.dumps({"bar": "moop"}),
            },
            format="multipart",
        )
        plugin_config_id = response.json()["id"]
        response = self.client.post(
            f"/api/plugin_config/{plugin_config_id}/job",
            {"job": {"type": "myJob", "payload": {"a": 1}, "operation": "stop"}},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        execute_fn = db_connections["default"].cursor().__enter__().execute
        self.assertEqual(execute_fn.call_count, 1)

        execute_fn_args = execute_fn.mock_calls[0].args
        self.assertEqual(execute_fn_args[0], "SELECT graphile_worker.add_job('pluginJob', %s)")
        self.assertDictEqual(
            json.loads(execute_fn_args[1][0]),
            {
                "type": "myJob",
                "payload": {"a": 1, "$operation": "stop", "$job_id": ANY},
                "pluginConfigId": plugin_config_id,
                "pluginConfigTeam": self.team.pk,
            },
        )

        mock_validate_plugin_job_payload.assert_called_with(ANY, "myJob", {"a": 1}, is_staff=False)

    def test_check_for_updates_plugins_reload_not_called(self, _, mock_reload):
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"url": "https://github.com/PostHog/helloworldplugin"},
        )
        self.assertEqual(mock_reload.call_count, 1)

        plugin_id = response.json()["id"]
        plugin = Plugin.objects.get(id=plugin_id)
        fake_date = datetime(2022, 1, 1, 0, 0).replace(tzinfo=ZoneInfo("UTC"))
        self.assertNotEqual(plugin.latest_tag_checked_at, fake_date)

        with freeze_time(fake_date.isoformat()):
            response = self.client.get(f"/api/organizations/@current/plugins/{plugin_id}/check_for_updates")
            plugin.refresh_from_db()

            # make sure the update did happen
            self.assertEqual(plugin.latest_tag_checked_at, fake_date)

            # make sure we didn't emit a signal to reload plugins again
            self.assertEqual(mock_reload.call_count, 1)

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_get_all_activity(self, _, mock_reload):
        self.organization.plugins_access_level = Organization.PluginsAccessLevel.INSTALL
        self.organization.save()
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"url": "https://github.com/PostHog/helloworldplugin"},
        )
        self.assertEqual(response.status_code, 201)

        plugin_id = response.json()["id"]
        response = self.client.post(
            "/api/plugin_config/",
            {
                "plugin": plugin_id,
                "enabled": True,
                "order": 0,
                "config": json.dumps({"bar": "moop"}),
            },
        )
        plugin_config_id = response.json()["id"]

        # We should get back activity for both Plugin and PluginConfig scopes
        self.assert_plugin_activity(
            [
                {
                    "activity": "installed",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "detail": {
                        "changes": None,
                        "trigger": None,
                        "type": None,
                        "name": "helloworldplugin",
                        "short_id": None,
                    },
                    "item_id": str(plugin_id),
                    "scope": "Plugin",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                },
                {
                    "activity": "enabled",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "detail": {
                        "changes": [],
                        "trigger": None,
                        "type": None,
                        "name": "helloworldplugin",
                        "short_id": None,
                    },
                    "item_id": str(plugin_config_id),
                    "scope": "PluginConfig",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                },
            ]
        )


class TestPluginsAccessLevelAPI(APIBaseTest):
    def test_root_check(self):
        self.organization.plugins_access_level = Organization.PluginsAccessLevel.ROOT
        self.organization.save()

        result_root = can_globally_manage_plugins(self.organization)
        result_install = can_install_plugins(self.organization)
        result_config = can_configure_plugins(self.organization)
        result_view = can_view_plugins(self.organization)

        self.assertTrue(result_root)
        self.assertTrue(result_install)
        self.assertTrue(result_config)
        self.assertTrue(result_view)

    def test_install_check(self):
        self.organization.plugins_access_level = Organization.PluginsAccessLevel.INSTALL
        self.organization.save()

        result_root = can_globally_manage_plugins(self.organization)
        result_install = can_install_plugins(self.organization)
        result_config = can_configure_plugins(self.organization)
        result_view = can_view_plugins(self.organization)

        self.assertFalse(result_root)
        self.assertTrue(result_install)
        self.assertTrue(result_config)
        self.assertTrue(result_view)

    def test_install_check_but_different_specific_id(self):
        self.organization.plugins_access_level = Organization.PluginsAccessLevel.INSTALL
        self.organization.save()

        result_install = can_install_plugins(self.organization, "5802AE1C-FA8E-4559-9D7A-3206E371A350")

        self.assertFalse(result_install)

    def test_config_check(self):
        self.organization.plugins_access_level = Organization.PluginsAccessLevel.CONFIG
        self.organization.save()

        result_root = can_globally_manage_plugins(self.organization)
        result_install = can_install_plugins(self.organization)
        result_config = can_configure_plugins(self.organization)
        result_view = can_view_plugins(self.organization)

        self.assertFalse(result_root)
        self.assertFalse(result_install)
        self.assertTrue(result_config)
        self.assertTrue(result_view)

    def test_config_check_with_id_str(self):
        self.organization.plugins_access_level = Organization.PluginsAccessLevel.CONFIG
        self.organization.save()
        organization_id = str(self.organization.id)

        result_root = can_globally_manage_plugins(organization_id)
        result_install = can_install_plugins(organization_id)
        result_config = can_configure_plugins(organization_id)
        result_view = can_view_plugins(organization_id)

        self.assertFalse(result_root)
        self.assertFalse(result_install)
        self.assertTrue(result_config)
        self.assertTrue(result_view)

    def test_none_check(self):
        self.organization.plugins_access_level = Organization.PluginsAccessLevel.NONE
        self.organization.save()

        result_root = can_globally_manage_plugins(self.organization)
        result_install = can_install_plugins(self.organization)
        result_config = can_configure_plugins(self.organization)
        result_view = can_view_plugins(self.organization)

        self.assertFalse(result_root)
        self.assertFalse(result_install)
        self.assertFalse(result_config)
        self.assertFalse(result_view)

    def test_no_org_check(self):
        result_root = can_globally_manage_plugins(None)
        result_install = can_install_plugins(None)
        result_config = can_configure_plugins(None)
        result_view = can_view_plugins(None)

        self.assertFalse(result_root)
        self.assertFalse(result_install)
        self.assertFalse(result_config)
        self.assertFalse(result_view)
