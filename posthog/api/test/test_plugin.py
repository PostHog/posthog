import base64
import json
from typing import Dict, cast
from unittest import mock
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from semantic_version import Version

from posthog.models import Plugin, PluginAttachment, PluginConfig
from posthog.models.organization import Organization, OrganizationMembership
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
from posthog.test.base import APIBaseTest
from posthog.version import VERSION


def mocked_plugin_reload(*args, **kwargs):
    pass


@mock.patch("posthog.models.plugin.reload_plugins_on_workers", side_effect=mocked_plugin_reload)
@mock.patch("requests.get", side_effect=mocked_plugin_requests_get)
class TestPluginAPI(APIBaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # We make sure the org has permissions for these tests, particularly for tests on posthog-cloud
        cls.organization.plugins_access_level = Organization.PluginsAccessLevel.ROOT
        cls.organization.save()

    def test_create_plugin_auth(self, mock_get, mock_reload):
        repo_url = "https://github.com/PostHog/helloworldplugin"

        for level in (Organization.PluginsAccessLevel.NONE, Organization.PluginsAccessLevel.CONFIG):
            self.organization.plugins_access_level = level
            self.organization.save()
            response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url})
            self.assertEqual(
                response.status_code, 403, "Did not reject plugin installation as non-install org properly"
            )

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.INSTALL
        self.organization.save()
        response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url})
        self.assertEqual(response.status_code, 201, "Did not manage to install plugin properly despite install access")

        response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url})
        self.assertEqual(response.status_code, 400, "Did not reject already installed plugin properly")

    def test_create_plugin_auth_globally_managed(self, mock_get, mock_reload):
        repo_url = "https://github.com/PostHog/helloworldplugin"

        for level in (
            Organization.PluginsAccessLevel.NONE,
            Organization.PluginsAccessLevel.CONFIG,
            Organization.PluginsAccessLevel.INSTALL,
        ):
            self.organization.plugins_access_level = level
            self.organization.save()
            response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url, "is_global": True})
            self.assertEqual(
                response.status_code,
                403,
                "Did not reject globally managed plugin installation as non-root org properly",
            )

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.ROOT
        self.organization.save()
        response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url, "is_global": True})
        self.assertEqual(
            response.status_code, 201, "Did not manage to install globally managed plugin properly despite root access"
        )

        response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url, "is_global": True})
        self.assertEqual(response.status_code, 400, "Did not reject already installed plugin properly")

    def test_globally_managed_visible_to_all_orgs(self, mock_get, mock_reload):
        my_org = self.organization
        other_org: Organization = Organization.objects.create(
            name="FooBar2", plugins_access_level=Organization.PluginsAccessLevel.CONFIG
        )
        OrganizationMembership.objects.create(user=self.user, organization=other_org)

        repo_url = "https://github.com/PostHog/helloworldplugin"
        install_response = self.client.post(f"/api/organizations/{my_org.id}/plugins/", {"url": repo_url})
        self.assertEqual(install_response.status_code, 201, "Did not manage to install plugin properly")
        # The plugin is NOT global and should only show up for my org
        list_response_other_org_1 = self.client.get(f"/api/organizations/{other_org.id}/plugins/")
        self.assertDictEqual(
            list_response_other_org_1.json(), {"count": 0, "next": None, "previous": None, "results": []}
        )
        self.assertEqual(list_response_other_org_1.status_code, 200)
        # Let's make the plugin global
        update_response_my_org = self.client.patch(
            f"/api/organizations/{my_org.id}/plugins/{install_response.json()['id']}/", {"is_global": True}
        )
        self.assertEqual(update_response_my_org.status_code, 200)
        # Now the plugin is global and should show up for other org
        list_response_other_org_2 = self.client.get(f"/api/organizations/{other_org.id}/plugins/")
        list_response_other_org_2_data = list_response_other_org_2.json()
        self.assertEqual(list_response_other_org_2_data["count"], 1)
        self.assertEqual(list_response_other_org_2.status_code, 200)

    def test_globally_managed_only_manageable_by_owner_org(self, mock_get, mock_reload):
        my_org = self.organization
        other_org: Organization = Organization.objects.create(
            name="FooBar2", plugins_access_level=Organization.PluginsAccessLevel.ROOT
        )
        OrganizationMembership.objects.create(user=self.user, organization=other_org)

        repo_url = "https://github.com/PostHog/helloworldplugin"
        install_response = self.client.post(
            f"/api/organizations/{my_org.id}/plugins/", {"url": repo_url, "is_global": True}
        )
        self.assertEqual(
            install_response.status_code, 201, "Did not manage to install globally managed plugin properly"
        )

        # My org
        patch_response_other_org_1 = self.client.patch(
            f"/api/organizations/{my_org.id}/plugins/{install_response.json()['id']}", {"description": "X"}
        )
        self.assertEqual(patch_response_other_org_1.status_code, 200)
        self.assertEqual("X", patch_response_other_org_1.json().get("description"))

        # Other org
        patch_response_other_org_2 = self.client.patch(
            f"/api/organizations/{other_org.id}/plugins/{install_response.json()['id']}", {"description": "Y"}
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
            for level in (Organization.PluginsAccessLevel.NONE, Organization.PluginsAccessLevel.CONFIG):
                self.organization.plugins_access_level = level
                self.organization.save()
                response = self.client.patch(
                    f"/api/organizations/@current/plugins/{install_response.json()['id']}/", {"is_global": False}
                )
                self.assertEqual(
                    response.status_code, 403, "Plugin was not 403 for org despite it having no plugin install access"
                )

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.INSTALL
        self.organization.save()
        for is_global in (True, False):
            response = self.client.patch(
                f"/api/organizations/@current/plugins/{install_response.json()['id']}/", {"is_global": is_global}
            )
            self.assertEqual(
                response.status_code, 403, "Did not reject globally managed plugin update as non-root org properly"
            )

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.ROOT
        self.organization.save()
        for is_global in (True, False):
            response = self.client.patch(
                f"/api/organizations/@current/plugins/{install_response.json()['id']}/", {"is_global": is_global}
            )
            self.assertEqual(
                response.status_code, 200, "Did not manage to make plugin globally managed properly despite root access"
            )

    def test_plugin_private_token_url_unique(self, mock_get, mock_reload):
        repo_url = "https://gitlab.com/mariusandra/helloworldplugin"
        response = self.client.post(
            "/api/organizations/@current/plugins/", {"url": "{}?private_token=123".format(repo_url)}
        )
        self.assertEqual(response.status_code, 201)
        response = self.client.post(
            "/api/organizations/@current/plugins/", {"url": "{}?private_token=123".format(repo_url)}
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url})
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            "/api/organizations/@current/plugins/", {"url": "{}?private_token=567".format(repo_url)}
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post("/api/organizations/@current/plugins/", {"url": "{}-other".format(repo_url)})
        self.assertEqual(response.status_code, 201)
        response = self.client.post(
            "/api/organizations/@current/plugins/", {"url": "{}-other?private_token=567".format(repo_url)}
        )
        self.assertEqual(response.status_code, 400)

    def test_update_plugin_auth(self, mock_get, mock_reload):
        repo_url = "https://github.com/PostHog/helloworldplugin"
        response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url})
        self.assertEqual(response.status_code, 201)

        api_url = f"/api/organizations/@current/plugins/{response.json()['id']}/upgrade"
        response = self.client.post(api_url, {"url": repo_url})
        self.assertEqual(response.status_code, 200)

        for level in (Organization.PluginsAccessLevel.NONE, Organization.PluginsAccessLevel.CONFIG):
            self.organization.plugins_access_level = level
            self.organization.save()
            response = self.client.post(api_url, {"url": repo_url})
            self.assertEqual(response.status_code, 403)

    def test_delete_plugin_auth(self, mock_get, mock_reload):
        repo_url = "https://github.com/PostHog/helloworldplugin"
        response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url})
        self.assertEqual(response.status_code, 201)

        api_url = "/api/organizations/@current/plugins/{}".format(response.json()["id"])

        for level in (Organization.PluginsAccessLevel.NONE, Organization.PluginsAccessLevel.CONFIG):
            self.organization.plugins_access_level = level
            self.organization.save()
            response = self.client.delete(api_url)
            self.assertEqual(response.status_code, 403)

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.INSTALL
        self.organization.save()
        response = self.client.delete(api_url)
        self.assertEqual(response.status_code, 204)

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
        response = self.client.post(f"/api/organizations/@current/plugins/", {"url": repo_url, "is_global": True})

        self.assertEqual(response.status_code, 201)

        api_url = f"/api/organizations/@current/plugins/{response.json()['id']}"
        response = self.client.delete(api_url)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json().get("detail"), "This plugin is marked as global! Make it local before uninstallation"
        )

    def test_create_plugin_repo_url(self, mock_get, mock_reload):
        self.assertEqual(mock_reload.call_count, 0)
        response = self.client.post(
            "/api/organizations/@current/plugins/", {"url": "https://github.com/PostHog/helloworldplugin"}
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
                "config_schema": {
                    "bar": {"name": "What's in the bar?", "type": "string", "default": "baz", "required": False},
                },
                "tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                "source": None,
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
        self.assertEqual(mock_reload.call_count, 1)

        self.client.delete("/api/organizations/@current/plugins/{}".format(response.json()["id"]))
        self.assertEqual(Plugin.objects.count(), 0)
        self.assertEqual(mock_reload.call_count, 2)

    def test_create_plugin_commit_url(self, mock_get, mock_reload):
        self.assertEqual(mock_reload.call_count, 0)
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"url": "https://github.com/PostHog/helloworldplugin/commit/{}".format(HELLO_WORLD_PLUGIN_GITHUB_ZIP[0])},
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
                "config_schema": {
                    "bar": {"name": "What's in the bar?", "type": "string", "default": "baz", "required": False},
                },
                "tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                "source": None,
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
                "url": "https://github.com/PostHog/helloworldplugin",
                "config_schema": {
                    "bar": {"name": "What's in the bar?", "type": "string", "default": "baz", "required": False},
                    "foodb": {"name": "Upload your database", "type": "attachment", "required": False},
                },
                "tag": HELLO_WORLD_PLUGIN_GITHUB_ATTACHMENT_ZIP[0],
                "source": None,
                "latest_tag": None,
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
        with self.settings(MULTI_TENANCY=False):
            response = self.client.post(
                "/api/organizations/@current/plugins/",
                {"url": f"https://github.com/posthog-plugin/version-equals/commit/{VERSION}"},
            )
            self.assertEqual(response.status_code, 201)

    def test_create_plugin_version_range_eq_next_minor(self, mock_get, mock_reload):
        with self.settings(MULTI_TENANCY=False):
            response = self.client.post(
                "/api/organizations/@current/plugins/",
                {"url": f"https://github.com/posthog-plugin/version-equals/commit/{Version(VERSION).next_minor()}"},
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                cast(Dict[str, str], response.json())["detail"],
                f'Currently running PostHog version {VERSION} does not match this plugin\'s semantic version requirement "{Version(VERSION).next_minor()}".',
            )

    def test_create_plugin_version_range_gt_current(self, mock_get, mock_reload):
        with self.settings(MULTI_TENANCY=False):
            response = self.client.post(
                "/api/organizations/@current/plugins/",
                {"url": f"https://github.com/posthog-plugin/version-greater-than/commit/0.0.0"},
            )
            self.assertEqual(response.status_code, 201)

    def test_create_plugin_version_range_gt_next_major(self, mock_get, mock_reload):
        with self.settings(MULTI_TENANCY=False):
            response = self.client.post(
                "/api/organizations/@current/plugins/",
                {
                    "url": f"https://github.com/posthog-plugin/version-greater-than/commit/{Version(VERSION).next_major()}"
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                cast(Dict[str, str], response.json())["detail"],
                f'Currently running PostHog version {VERSION} does not match this plugin\'s semantic version requirement ">= {Version(VERSION).next_major()}".',
            )

    def test_create_plugin_version_range_lt_current(self, mock_get, mock_reload):
        with self.settings(MULTI_TENANCY=False):
            response = self.client.post(
                "/api/organizations/@current/plugins/",
                {"url": f"https://github.com/posthog-plugin/version-less-than/commit/{VERSION}"},
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                cast(Dict[str, str], response.json())["detail"],
                f'Currently running PostHog version {VERSION} does not match this plugin\'s semantic version requirement "< {VERSION}".',
            )

    def test_create_plugin_version_range_lt_next_major(self, mock_get, mock_reload):
        with self.settings(MULTI_TENANCY=False):
            response = self.client.post(
                "/api/organizations/@current/plugins/",
                {"url": f"https://github.com/posthog-plugin/version-less-than/commit/{Version(VERSION).next_major()}"},
            )
            self.assertEqual(response.status_code, 201)

    def test_create_plugin_version_range_lt_invalid(self, mock_get, mock_reload):
        with self.settings(MULTI_TENANCY=False):
            response = self.client.post(
                "/api/organizations/@current/plugins/",
                {"url": f"https://github.com/posthog-plugin/version-less-than/commit/..."},
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                cast(Dict[str, str], response.json())["detail"], 'Invalid PostHog semantic version requirement "< ..."!'
            )

    def test_create_plugin_version_range_gt_next_major_ignore_on_cloud(self, mock_get, mock_reload):
        with self.settings(MULTI_TENANCY=True):
            response = self.client.post(
                "/api/organizations/@current/plugins/",
                {
                    "url": f"https://github.com/posthog-plugin/version-greater-than/commit/{Version(VERSION).next_major()}"
                },
            )
            self.assertEqual(response.status_code, 201)

    def test_create_plugin_source(self, mock_get, mock_reload):
        self.assertEqual(mock_reload.call_count, 0)
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"plugin_type": "source", "name": "myplugin", "source": "const processEvent = e => e",},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json(),
            {
                "id": response.json()["id"],
                "plugin_type": "source",
                "name": "myplugin",
                "description": None,
                "url": None,
                "config_schema": {},
                "tag": None,
                "source": "const processEvent = e => e",
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
        self.assertEqual(mock_reload.call_count, 1)

        self.client.delete("/api/organizations/@current/plugins/{}".format(response.json()["id"]))
        self.assertEqual(Plugin.objects.count(), 0)
        self.assertEqual(mock_reload.call_count, 2)

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
                    "verified": False,
                    "maintainer": "official",
                },
                {
                    "name": "helloworldplugin",
                    "url": "https://github.com/posthog/helloworldplugin",
                    "description": "Greet the World and Foo a Bar",
                    "verified": True,
                    "maintainer": "community",
                },
            ],
        )

    def test_install_plugin_on_multiple_orgs(self, mock_get, mock_reload):
        my_org = self.organization
        other_org = Organization.objects.create(
            name="FooBar2", plugins_access_level=Organization.PluginsAccessLevel.INSTALL
        )
        response = self.client.post(
            "/api/organizations/{}/plugins/".format(my_org.id), {"url": "https://github.com/PostHog/helloworldplugin"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Plugin.objects.count(), 1)
        response = self.client.post(
            "/api/organizations/{}/plugins/".format(my_org.id), {"url": "https://github.com/PostHog/helloworldplugin"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Plugin.objects.count(), 1)

        # try to save it for another org
        response = self.client.post(
            "/api/organizations/{}/plugins/".format(other_org.id),
            {"url": "https://github.com/PostHog/helloworldplugin"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Plugin.objects.count(), 1)

        self.user.join(organization=other_org, level=OrganizationMembership.Level.OWNER)
        response = self.client.post(
            "/api/organizations/{}/plugins/".format(other_org.id),
            {"url": "https://github.com/PostHog/helloworldplugin"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Plugin.objects.count(), 2)
        response = self.client.post(
            "/api/organizations/{}/plugins/".format(other_org.id),
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

    def test_create_plugin_config(self, mock_get, mock_reload):
        self.assertEqual(mock_reload.call_count, 0)
        response = self.client.post(
            "/api/organizations/@current/plugins/", {"url": "https://github.com/PostHog/helloworldplugin"}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginConfig.objects.count(), 0)
        plugin_id = response.json()["id"]
        response = self.client.post(
            "/api/plugin_config/",
            {"plugin": plugin_id, "enabled": True, "order": 0, "config": json.dumps({"bar": "moop"})},
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
                "config": {"bar": "moop"},
                "error": None,
                "team_id": self.team.pk,
            },
        )
        response = self.client.patch(
            "/api/plugin_config/{}".format(plugin_config_id),
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
            },
        )
        self.client.delete("/api/plugin_config/{}".format(plugin_config_id))
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginConfig.objects.count(), 1)

    def test_create_plugin_config_auth(self, mock_get, mock_reload):
        response = self.client.post(
            "/api/organizations/@current/plugins/", {"url": "https://github.com/PostHog/helloworldplugin"}
        )
        plugin_id = response.json()["id"]

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.NONE
        self.organization.save()
        response = self.client.post(
            "/api/plugin_config/",
            {"plugin": plugin_id, "enabled": True, "order": 0, "config": json.dumps({"bar": "moop"})},
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
                {"plugin": plugin_id, "enabled": True, "order": 0, "config": json.dumps({"bar": "moop"})},
                format="multipart",
            )
            self.assertEqual(response.status_code, 201)

    def test_update_plugin_config_auth(self, mock_get, mock_reload):
        response = self.client.post(
            "/api/organizations/@current/plugins/", {"url": "https://github.com/PostHog/helloworldplugin"}
        )
        plugin_id = response.json()["id"]
        response = self.client.post(
            "/api/plugin_config/",
            {"plugin": plugin_id, "enabled": True, "order": 0, "config": json.dumps({"bar": "moop"})},
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
                "/api/plugin_config/{}".format(plugin_config_id),
                {"enabled": False, "order": 1, "config": json.dumps({"bar": "soup"})},
                format="multipart",
            )
            self.assertEqual(response.status_code, 200)

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.NONE
        self.organization.save()
        response = self.client.patch(
            "/api/plugin_config/{}".format(plugin_config_id),
            {"enabled": False, "order": 1, "config": json.dumps({"bar": "soup"})},
            format="multipart",
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_plugin_config_auth(self, mock_get, mock_reload):
        response = self.client.post(
            "/api/organizations/@current/plugins/", {"url": "https://github.com/PostHog/helloworldplugin"}
        )
        plugin_id = response.json()["id"]
        response = self.client.post(
            "/api/plugin_config/",
            {"plugin": plugin_id, "enabled": True, "order": 0, "config": json.dumps({"bar": "moop"})},
            format="multipart",
        )
        plugin_config_id = response.json()["id"]

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.NONE
        self.organization.save()
        response = self.client.delete("/api/plugin_config/{}".format(plugin_config_id))
        self.assertEqual(response.status_code, 404)

        for level in (
            Organization.PluginsAccessLevel.ROOT,
            Organization.PluginsAccessLevel.INSTALL,
            Organization.PluginsAccessLevel.CONFIG,
        ):
            self.organization.plugins_access_level = level
            self.organization.save()
            response = self.client.delete("/api/plugin_config/{}".format(plugin_config_id))
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

        response = self.client.get("/api/plugin_config/{}".format(plugin_config_id))
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
            "/api/plugin_config/{}".format(plugin_config_id), {"add_attachment[foodb]": tmp_file_2}, format="multipart",
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
            "/api/plugin_config/{}".format(plugin_config_id), {"remove_attachment[foodb]": True}, format="multipart",
        )
        self.assertEqual(response.json()["config"], {"bar": "moop"})
        self.assertEqual(PluginAttachment.objects.count(), 0)

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
            {"plugin": plugin_id, "enabled": True, "order": 0, "config": json.dumps({"bar": "very secret value"})},
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
            },
        )

        # Test a config change and that an empty config is returned to the client instead of the secret placeholder
        response = self.client.patch(
            "/api/plugin_config/{}".format(plugin_config_id),
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
            },
        )

        # Test that secret values are updated but never revealed
        response = self.client.patch(
            "/api/plugin_config/{}".format(plugin_config_id),
            {"enabled": False, "order": 1, "config": json.dumps({"bar": "a new very secret value"})},
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
            },
        )
        plugin_config = PluginConfig.objects.get(plugin=plugin_id)
        self.assertEqual(plugin_config.config, {"bar": "a new very secret value"})

    @patch("posthog.api.plugin.celery_app.send_task")
    def test_job_trigger(self, patch_trigger_plugin_job, mock_get, mock_reload):
        response = self.client.post(
            "/api/organizations/@current/plugins/", {"url": "https://github.com/PostHog/helloworldplugin"}
        )
        plugin_id = response.json()["id"]
        response = self.client.post(
            "/api/plugin_config/",
            {"plugin": plugin_id, "enabled": True, "order": 0, "config": json.dumps({"bar": "moop"})},
            format="multipart",
        )
        plugin_config_id = response.json()["id"]
        response = self.client.post(
            "/api/plugin_config/{}/job".format(plugin_config_id),
            {"job": {"type": "myJob", "payload": {"a": 1}, "operation": "stop"}},
            format="json",
        )

        patch_trigger_plugin_job.assert_has_calls(
            [
                mock.call(
                    name="posthog.tasks.plugins.plugin_job",
                    queue="posthog-plugins",
                    args=[self.team.pk, plugin_config_id, "myJob", "stop", {"a": 1}],
                )
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
