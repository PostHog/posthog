import json
from datetime import datetime
from typing import Optional, cast
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, QueryMatchingTest, snapshot_postgres_queries
from unittest import mock

from rest_framework import status

from posthog.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.constants import FROZEN_POSTHOG_VERSION
from posthog.models import Plugin, PluginConfig, PluginSourceFile
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.plugins.access import can_configure_plugins, can_globally_manage_plugins, can_install_plugins
from posthog.plugins.test.mock import mocked_plugin_requests_get
from posthog.plugins.test.plugin_archives import HELLO_WORLD_PLUGIN_GITHUB_ATTACHMENT_ZIP, HELLO_WORLD_PLUGIN_GITHUB_ZIP
from posthog.queries.app_metrics.test.test_app_metrics import create_app_metric


def mocked_plugin_reload(*args, **kwargs):
    pass


@mock.patch("posthog.models.plugin.reload_plugins_on_workers", side_effect=mocked_plugin_reload)
@mock.patch("requests.get", side_effect=mocked_plugin_requests_get)
class TestPluginAPI(APIBaseTest, QueryMatchingTest):
    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # We make sure the org has permissions for these tests
        cls.organization.plugins_access_level = Organization.PluginsAccessLevel.ROOT
        cls.organization.save()

    def setUp(self):
        super().setUp()
        sync_template_to_db(MOCK_NODE_TEMPLATES[12])
        sync_template_to_db(MOCK_NODE_TEMPLATES[16])

    def _get_plugin_activity(self, expected_status: int = status.HTTP_200_OK):
        activity = self.client.get(f"/api/organizations/@current/plugins/activity")
        self.assertEqual(activity.status_code, expected_status)
        return activity.json()

    def assert_plugin_activity(self, expected: list[dict]):
        activity_response = self._get_plugin_activity()

        activity: list[dict] = activity_response["results"]
        self.maxDiff = None
        self.assertEqual(activity, expected)

    def _create_plugin(
        self, additional_params: Optional[dict] = None, expected_status: int = status.HTTP_201_CREATED
    ) -> dict:
        params = {"url": "https://github.com/PostHog/helloworldplugin"}

        if additional_params:
            params.update(additional_params)

        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"url": "https://github.com/PostHog/helloworldplugin"},
        )

        assert response.status_code == expected_status, response.json()
        return response.json()

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
        # To make sure it works properly the user in question shouldn't also belong to the organization that owns the plugin
        User.objects.create_and_join(
            organization=other_org, email="test@test.com", password="123456", first_name="Test"
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
        self.assertEqual(list_response_other_org_2.status_code, 200)
        self.assertEqual(list_response_other_org_2_data["count"], 1)

        single_plugin_other_org_2 = self.client.get(
            f"/api/organizations/{other_org.id}/plugins/{install_response.json()['id']}"
        )
        single_plugin_other_org_2_data = single_plugin_other_org_2.json()
        self.assertEqual(single_plugin_other_org_2.status_code, 200)
        self.assertEqual(single_plugin_other_org_2_data["id"], install_response.json()["id"])

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

    def test_delete_plugin_auth(self, mock_get, mock_reload):
        with freeze_time("2021-08-25T22:09:14.252Z"):
            repo_url = "https://github.com/PostHog/helloworldplugin"
            response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url})
            self.assertEqual(response.status_code, 201)

        with freeze_time("2021-08-25T22:09:14.253Z"):
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
                    "activity": "uninstalled",
                    "created_at": "2021-08-25T22:09:14.253000Z",
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
                "hog_function_migration_available": False,
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
                "hog_function_migration_available": False,
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
                "hog_function_migration_available": False,
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
                cast(dict[str, str], response.json())["detail"],
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
                cast(dict[str, str], response.json())["detail"],
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
                cast(dict[str, str], response.json())["detail"],
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
                cast(dict[str, str], response.json())["detail"],
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

    def test_transpile_plugin_frontend_source(self, mock_get, mock_reload):
        # Setup
        assert mock_reload.call_count == 0
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"plugin_type": "source", "name": "myplugin"},
        )
        assert response.status_code == 201
        id = response.json()["id"]
        assert response.json() == {
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
            "hog_function_migration_available": False,
        }

        assert Plugin.objects.count() == 1
        assert mock_reload.call_count == 0

        # Add first source file, frontend.tsx
        self.client.patch(
            f"/api/organizations/@current/plugins/{id}/update_source",
            {"frontend.tsx": "export const scene = {}"},
        )
        assert Plugin.objects.count() == 1
        assert PluginSourceFile.objects.count() == 1
        assert mock_reload.call_count == 1

        # Fetch transpiled source via API call
        plugin = Plugin.objects.get(pk=id)
        plugin_config = PluginConfig.objects.create(plugin=plugin, team=self.team, enabled=True, order=1)
        response = self.client.get(f"/api/plugin_config/{plugin_config.id}/frontend")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.content.decode("utf-8"),
            '"use strict";\nexport function getFrontendApp (require) { let exports = {}; '
            '"use strict";\n\nObject.defineProperty(exports, "__esModule", {\n  value: true\n});\nexports.scene = void 0;\n'
            "var scene = exports.scene = {};"  # this is it
            "; return exports; }",
        )

        # Check in the database
        plugin_source = PluginSourceFile.objects.get(plugin_id=id)
        assert plugin_source.source == "export const scene = {}"
        assert plugin_source.error is None
        assert plugin_source.transpiled == response.content.decode("utf-8")
        assert plugin_source.status == PluginSourceFile.Status.TRANSPILED

        # Updates work
        self.client.patch(
            f"/api/organizations/@current/plugins/{id}/update_source",
            {"frontend.tsx": "export const scene = { name: 'new' }"},
        )
        plugin_source = PluginSourceFile.objects.get(plugin_id=id)
        assert plugin_source.source == "export const scene = { name: 'new' }"
        assert plugin_source.error is None
        assert (
            plugin_source.transpiled
            == (
                '"use strict";\nexport function getFrontendApp (require) { let exports = {}; "use strict";\n\n'
                'Object.defineProperty(exports, "__esModule", {\n  value: true\n});\nexports.scene = void 0;\n'
                "var scene = exports.scene = {\n  name: 'new'\n};"  # this is it
                "; return exports; }"
            )
        )
        assert plugin_source.status == PluginSourceFile.Status.TRANSPILED

        # Errors as well
        self.client.patch(
            f"/api/organizations/@current/plugins/{id}/update_source",
            {"frontend.tsx": "export const scene = { nam broken code foobar"},
        )
        plugin_source = PluginSourceFile.objects.get(plugin_id=id)
        assert plugin_source.source == "export const scene = { nam broken code foobar"
        assert plugin_source.transpiled is None
        assert plugin_source.status == PluginSourceFile.Status.ERROR
        assert (
            plugin_source.error
            == '/frontend.tsx: Unexpected token, expected "," (1:27)\n\n> 1 | export const scene = { nam broken code foobar\n    |                            ^\n'
        )

        # Deletes work
        self.client.patch(
            f"/api/organizations/@current/plugins/{id}/update_source",
            {"frontend.tsx": None},
        )
        try:
            PluginSourceFile.objects.get(plugin_id=id)
            raise AssertionError("Should have thrown DoesNotExist")
        except PluginSourceFile.DoesNotExist:
            assert True

        # Check that the syntax for "site.ts" is slightly different
        self.client.patch(
            f"/api/organizations/@current/plugins/{id}/update_source",
            {"site.ts": "console.log('hello')"},
        )
        plugin_source = PluginSourceFile.objects.get(plugin_id=id)
        assert plugin_source.source == "console.log('hello')"
        assert plugin_source.error is None
        assert (
            plugin_source.transpiled
            == "(function () {let exports={};\"use strict\";\n\nconsole.log('hello');;return exports;})"
        )
        assert plugin_source.status == PluginSourceFile.Status.TRANSPILED

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
        # Expectation: since plugins are url-unique, installing the same plugin on a second orgs should
        # return a 400 response, as the plugin is already installed on the first org
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
        # Fails due to org membership
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Plugin.objects.count(), 1)

        self.user.join(organization=other_org, level=OrganizationMembership.Level.OWNER)

        response = self.client.post(
            f"/api/organizations/{other_org.id}/plugins/",
            {"url": "https://github.com/PostHog/helloworldplugin"},
        )
        # Fails since the plugin already exists
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Plugin.objects.count(), 1)

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

    def test_can_access_global_plugin_even_if_not_in_org(self, mock_get, mock_reload):
        other_org = Organization.objects.create(
            name="Foo", plugins_access_level=Organization.PluginsAccessLevel.INSTALL
        )
        other_orgs_plugin = Plugin.objects.create(organization=other_org, is_global=True)
        res = self.client.get(f"/api/organizations/@current/plugins/{other_orgs_plugin.id}/")
        assert res.status_code == 200, res.json()

    @snapshot_postgres_queries
    def test_listing_plugins_is_not_nplus1(self, _mock_get, _mock_reload) -> None:
        with self.assertNumQueries(10):
            self._assert_number_of_when_listed_plugins(0)

        Plugin.objects.create(organization=self.organization)

        with self.assertNumQueries(10):
            self._assert_number_of_when_listed_plugins(1)

        Plugin.objects.create(organization=self.organization)

        with self.assertNumQueries(10):
            self._assert_number_of_when_listed_plugins(2)

        Plugin.objects.create(organization=self.organization)

        with self.assertNumQueries(10):
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
                "name": "name in ui",
                "description": "description in ui",
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 400, response.content)

        assert "Plugin creation is no longer possible" in response.content.decode("utf-8")

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

    def test_retrieving_plugin_config_logs_empty(self, mock_get, mock_reload):
        plugin = Plugin.objects.create(organization=self.organization)
        plugin_config = PluginConfig.objects.create(plugin=plugin, enabled=True, team=self.team, order=0)

        response = self.client.get(f"/api/environments/{self.team.pk}/plugin_configs/{plugin_config.id}/logs/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"count": 0, "next": None, "previous": None, "results": []})

    @freeze_time("2021-12-05T13:23:00Z")
    def test_plugin_config_list(self, mock_get, mock_reload):
        plugin = Plugin.objects.create(organization=self.organization)
        plugin_config1 = PluginConfig.objects.create(plugin=plugin, team=self.team, enabled=True, order=1)
        plugin_config2 = PluginConfig.objects.create(
            plugin=plugin,
            team=self.team,
            enabled=True,
            order=2,
            name="ui name",
            description="ui description",
        )
        PluginConfig.objects.create(plugin=plugin, team=self.team, order=3, deleted=True)

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
                    "updated_at": mock.ANY,
                    "name": None,
                    "description": None,
                    "deleted": False,
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
                    "updated_at": mock.ANY,
                    "name": "ui name",
                    "description": "ui description",
                    "deleted": False,
                },
            ],
        )

    def test_create_hog_function_from_plugin_config(self, mock_get, mock_reload):
        mock_geoip_plugin = Plugin.objects.create(
            organization=self.organization,
            plugin_type="local",
            name="GeoIP",
            description="Get the GeoIP of the user",
            url="https://github.com/PostHog/posthog-plugin-geoip",
        )

        response = self.client.post(
            "/api/plugin_config/",
            {
                "plugin": mock_geoip_plugin.id,
                "enabled": True,
                "order": 1,
                "config": json.dumps({"bar": "very secret value"}),
            },
            format="multipart",
        )

        assert response.status_code == 201, response.json()

        assert PluginConfig.objects.count() == 0
        hog_function = HogFunction.objects.all()
        assert hog_function.count() == 1
        assert hog_function[0].template_id == "plugin-posthog-plugin-geoip"
        assert hog_function[0].type == "transformation"
        assert hog_function[0].name == "GeoIP"
        assert hog_function[0].description == "Enrich events with GeoIP data"
        assert hog_function[0].filters == {
            "source": "events",
            "bytecode": ["_H", 1, 29],
        }  # Assert the compiled bytecode for empty filter
        assert hog_function[0].hog == "return event"
        assert hog_function[0].enabled
        assert hog_function[0].team == self.team
        assert hog_function[0].created_by == self.user
        assert hog_function[0].icon_url == "/static/transformations/geoip.png"
        assert hog_function[0].inputs_schema == []
        assert hog_function[0].execution_order == 1
        assert hog_function[0].inputs == {}

    def test_create_hog_function_from_plugin_config_with_inputs(self, mock_get, mock_reload):
        mock_geoip_plugin = Plugin.objects.create(
            organization=self.organization,
            plugin_type="local",
            name="Taxonomy",
            description="",
            url="https://github.com/PostHog/taxonomy-plugin",
        )

        response = self.client.post(
            "/api/plugin_config/",
            {
                "plugin": mock_geoip_plugin.id,
                "enabled": True,
                "order": 0,
                "config": json.dumps({"defaultNamingConvention": "snake_case", "other": "to be removed"}),
            },
            format="multipart",
        )

        assert response.status_code == 201, response.json()

        assert PluginConfig.objects.count() == 0
        hog_function = HogFunction.objects.all()
        assert hog_function.count() == 1
        assert hog_function[0].template_id == "plugin-taxonomy-plugin"
        assert hog_function[0].inputs == {
            "defaultNamingConvention": {
                "order": 0,
                "value": "snake_case",
            },
        }

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


class TestPluginsAccessLevelAPI(APIBaseTest):
    def test_root_check(self):
        self.organization.plugins_access_level = Organization.PluginsAccessLevel.ROOT
        self.organization.save()

        result_root = can_globally_manage_plugins(self.organization)
        result_install = can_install_plugins(self.organization)
        result_config = can_configure_plugins(self.organization)

        self.assertTrue(result_root)
        self.assertTrue(result_install)
        self.assertTrue(result_config)

    def test_install_check(self):
        self.organization.plugins_access_level = Organization.PluginsAccessLevel.INSTALL
        self.organization.save()

        result_root = can_globally_manage_plugins(self.organization)
        result_install = can_install_plugins(self.organization)
        result_config = can_configure_plugins(self.organization)

        self.assertFalse(result_root)
        self.assertTrue(result_install)
        self.assertTrue(result_config)

    def test_config_check(self):
        self.organization.plugins_access_level = Organization.PluginsAccessLevel.CONFIG
        self.organization.save()

        result_root = can_globally_manage_plugins(self.organization)
        result_install = can_install_plugins(self.organization)
        result_config = can_configure_plugins(self.organization)

        self.assertFalse(result_root)
        self.assertFalse(result_install)
        self.assertTrue(result_config)

    def test_config_check_with_id_str(self):
        self.organization.plugins_access_level = Organization.PluginsAccessLevel.CONFIG
        self.organization.save()
        organization_id = str(self.organization.id)

        result_root = can_globally_manage_plugins(organization_id)
        result_install = can_install_plugins(organization_id)
        result_config = can_configure_plugins(organization_id)

        self.assertFalse(result_root)
        self.assertFalse(result_install)
        self.assertTrue(result_config)

    def test_none_check(self):
        self.organization.plugins_access_level = Organization.PluginsAccessLevel.NONE
        self.organization.save()

        result_root = can_globally_manage_plugins(self.organization)
        result_install = can_install_plugins(self.organization)
        result_config = can_configure_plugins(self.organization)

        self.assertFalse(result_root)
        self.assertFalse(result_install)
        self.assertFalse(result_config)

    def test_no_org_check(self):
        result_root = can_globally_manage_plugins(None)
        result_install = can_install_plugins(None)
        result_config = can_configure_plugins(None)

        self.assertFalse(result_root)
        self.assertFalse(result_install)
        self.assertFalse(result_config)
