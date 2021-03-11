import base64
import json
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.timezone import now

from posthog.models import Plugin, PluginAttachment, PluginConfig
from posthog.models.organization import Organization, OrganizationMembership
from posthog.plugins.access import can_configure_plugins_via_api, can_install_plugins_via_api
from posthog.plugins.test.mock import mocked_plugin_requests_get
from posthog.plugins.test.plugin_archives import (
    HELLO_WORLD_PLUGIN_GITHUB_ATTACHMENT_ZIP,
    HELLO_WORLD_PLUGIN_GITHUB_ZIP,
    HELLO_WORLD_PLUGIN_SECRET_GITHUB_ZIP,
)
from posthog.redis import get_client
from posthog.test.base import APIBaseTest


def mocked_plugin_reload(*args, **kwargs):
    pass


@mock.patch("posthog.api.plugin.reload_plugins_on_workers", side_effect=mocked_plugin_reload)
@mock.patch("requests.get", side_effect=mocked_plugin_requests_get)
class TestPluginAPI(APIBaseTest):
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
        update_response_my_org = self.client.patch(f"/api/organizations/{my_org.id}/plugins/{install_response.data['id']}/", {"is_global": True})  # type: ignore
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
        other_membership: OrganizationMembership = OrganizationMembership.objects.create(
            user=self.user, organization=other_org
        )

        repo_url = "https://github.com/PostHog/helloworldplugin"
        install_response = self.client.post(
            f"/api/organizations/{my_org.id}/plugins/", {"url": repo_url, "is_global": True}
        )
        self.assertEqual(
            install_response.status_code, 201, "Did not manage to install globally managed plugin properly"
        )

        # My org
        patch_response_other_org_1 = self.client.patch(f"/api/organizations/{my_org.id}/plugins/{install_response.data['id']}", {"description": "X"})  # type: ignore
        self.assertEqual(patch_response_other_org_1.status_code, 200)
        self.assertEqual("X", patch_response_other_org_1.json().get("description"))

        # Other org
        patch_response_other_org_2 = self.client.patch(f"/api/organizations/{other_org.id}/plugins/{install_response.data['id']}", {"description": "Y"})  # type: ignore
        self.assertEqual(patch_response_other_org_2.status_code, 403)
        self.assertTrue(
            "This plugin is managed by another organization:" in patch_response_other_org_2.json().get("detail")
        )

    def test_update_plugin_auth_to_globally_managed(self, mock_get, mock_reload):
        repo_url = "https://github.com/PostHog/helloworldplugin"
        install_response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url})
        self.assertEqual(install_response.status_code, 201)

        for is_global in (True, False):
            for level in (Organization.PluginsAccessLevel.NONE, Organization.PluginsAccessLevel.CONFIG):
                self.organization.plugins_access_level = level
                self.organization.save()
                response = self.client.patch(f"/api/organizations/@current/plugins/{install_response.data['id']}/", {"is_global": False})  # type: ignore
                self.assertEqual(
                    response.status_code, 404, "Plugin was not 404 for org despite it having no plugin install acces`s"
                )

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.INSTALL
        self.organization.save()
        for is_global in (True, False):
            response = self.client.patch(f"/api/organizations/@current/plugins/{install_response.data['id']}/", {"is_global": is_global})  # type: ignore
            self.assertEqual(
                response.status_code, 403, "Did not reject globally managed plugin update as non-root org properly"
            )

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.ROOT
        self.organization.save()
        for is_global in (True, False):
            response = self.client.patch(f"/api/organizations/@current/plugins/{install_response.data['id']}/", {"is_global": is_global})  # type: ignore
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

        api_url = f"/api/organizations/@current/plugins/{response.data['id']}/upgrade"  # type: ignore
        response = self.client.post(api_url, {"url": repo_url})
        self.assertEqual(response.status_code, 200)

        for level in (Organization.PluginsAccessLevel.NONE, Organization.PluginsAccessLevel.CONFIG):
            self.organization.plugins_access_level = level
            self.organization.save()
            response = self.client.post(api_url, {"url": repo_url})
            self.assertEqual(response.status_code, 404)

    def test_delete_plugin_auth(self, mock_get, mock_reload):
        repo_url = "https://github.com/PostHog/helloworldplugin"
        response = self.client.post("/api/organizations/@current/plugins/", {"url": repo_url})
        self.assertEqual(response.status_code, 201)

        api_url = "/api/organizations/@current/plugins/{}".format(response.data["id"])  # type: ignore

        for level in (Organization.PluginsAccessLevel.NONE, Organization.PluginsAccessLevel.CONFIG):
            self.organization.plugins_access_level = level
            self.organization.save()
            response = self.client.delete(api_url)
            self.assertEqual(response.status_code, 404)

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.INSTALL
        self.organization.save()
        response = self.client.delete(api_url)
        self.assertEqual(response.status_code, 204)

    def test_create_plugin_repo_url(self, mock_get, mock_reload):
        self.assertEqual(mock_reload.call_count, 0)
        response = self.client.post(
            "/api/organizations/@current/plugins/", {"url": "https://github.com/PostHog/helloworldplugin"}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.data,
            {
                "id": response.data["id"],  # type: ignore
                "plugin_type": "custom",
                "name": "helloworldplugin",
                "description": "Greet the World and Foo a Bar, JS edition!",
                "url": "https://github.com/PostHog/helloworldplugin",
                "config_schema": {
                    "bar": {"name": "What's in the bar?", "type": "string", "default": "baz", "required": False,},
                },
                "tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                "source": None,
                "latest_tag": None,
                "is_global": False,
                "organization_id": response.data["organization_id"],  # type: ignore
                "organization_name": self.CONFIG_ORGANIZATION_NAME,
            },
        )
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(mock_reload.call_count, 1)

        self.client.delete("/api/organizations/@current/plugins/{}".format(response.data["id"]))  # type: ignore
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
            response.data,
            {
                "id": response.data["id"],  # type: ignore
                "plugin_type": "custom",
                "name": "helloworldplugin",
                "description": "Greet the World and Foo a Bar, JS edition!",
                "url": "https://github.com/PostHog/helloworldplugin",
                "config_schema": {
                    "bar": {"name": "What's in the bar?", "type": "string", "default": "baz", "required": False,},
                },
                "tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                "source": None,
                "latest_tag": None,
                "is_global": False,
                "organization_id": response.data["organization_id"],  # type: ignore
                "organization_name": self.CONFIG_ORGANIZATION_NAME,
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
            response2.data,
            {
                "id": response2.data["id"],  # type: ignore
                "plugin_type": "custom",
                "name": "helloworldplugin",
                "description": "Greet the World and Foo a Bar, JS edition, vol 2!",
                "url": "https://github.com/PostHog/helloworldplugin",
                "config_schema": {
                    "bar": {"name": "What's in the bar?", "type": "string", "default": "baz", "required": False,},
                    "foodb": {"name": "Upload your database", "type": "attachment", "required": False,},
                },
                "tag": HELLO_WORLD_PLUGIN_GITHUB_ATTACHMENT_ZIP[0],
                "source": None,
                "latest_tag": None,
                "is_global": False,
                "organization_id": response2.data["organization_id"],  # type: ignore
                "organization_name": self.CONFIG_ORGANIZATION_NAME,
            },
        )
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(mock_reload.call_count, 1)

    def test_create_plugin_source(self, mock_get, mock_reload):
        self.assertEqual(mock_reload.call_count, 0)
        response = self.client.post(
            "/api/organizations/@current/plugins/",
            {"plugin_type": "source", "name": "myplugin", "source": "const processEvent = e => e",},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.data,
            {
                "id": response.data["id"],  # type: ignore
                "plugin_type": "source",
                "name": "myplugin",
                "description": None,
                "url": None,
                "config_schema": {},
                "tag": None,
                "source": "const processEvent = e => e",
                "latest_tag": None,
                "is_global": False,
                "organization_id": response.data["organization_id"],  # type: ignore
                "organization_name": self.CONFIG_ORGANIZATION_NAME,
            },
        )
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(mock_reload.call_count, 1)

        self.client.delete("/api/organizations/@current/plugins/{}".format(response.data["id"]))  # type: ignore
        self.assertEqual(Plugin.objects.count(), 0)
        self.assertEqual(mock_reload.call_count, 2)

    def test_plugin_repository(self, mock_get, mock_reload):
        response = self.client.get("/api/organizations/@current/plugins/repository/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
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
        for level in (Organization.PluginsAccessLevel.NONE, Organization.PluginsAccessLevel.CONFIG):
            self.organization.plugins_access_level = level
            self.organization.save()
            response = self.client.get("/api/organizations/@current/plugins/repository/")
            self.assertEqual(response.status_code, 403)

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.INSTALL
        self.organization.save()
        with self.settings(MULTI_TENANCY=True):  # Repository is only available to root orgs on Cloud
            response = self.client.get("/api/organizations/@current/plugins/repository/")
            self.assertEqual(response.status_code, 403)
        with self.settings(MULTI_TENANCY=False):
            response = self.client.get("/api/organizations/@current/plugins/repository/")
            self.assertEqual(response.status_code, 200)

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.ROOT
        self.organization.save()
        with self.settings(MULTI_TENANCY=True):
            response = self.client.get("/api/organizations/@current/plugins/repository/")
            self.assertEqual(response.status_code, 200)

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
        plugin_id = response.data["id"]  # type: ignore
        response = self.client.post(
            "/api/plugin_config/",
            {"plugin": plugin_id, "enabled": True, "order": 0, "config": json.dumps({"bar": "moop"})},
        )
        plugin_config_id = response.data["id"]  # type: ignore
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginConfig.objects.count(), 1)
        self.assertEqual(
            response.data,
            {
                "id": plugin_config_id,
                "plugin": plugin_id,
                "enabled": True,
                "order": 0,
                "config": {"bar": "moop"},
                "error": None,
            },
        )
        response = self.client.patch(
            "/api/plugin_config/{}".format(plugin_config_id),
            {"enabled": False, "order": 1, "config": json.dumps({"bar": "soup"})},
        )
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginConfig.objects.count(), 1)
        self.assertEqual(
            response.data,
            {
                "id": plugin_config_id,
                "plugin": plugin_id,
                "enabled": False,
                "order": 1,
                "config": {"bar": "soup"},
                "error": None,
            },
        )
        self.client.delete("/api/plugin_config/{}".format(plugin_config_id))
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginConfig.objects.count(), 1)

    def test_create_plugin_config_auth(self, mock_get, mock_reload):
        response = self.client.post(
            "/api/organizations/@current/plugins/", {"url": "https://github.com/PostHog/helloworldplugin"}
        )
        plugin_id = response.data["id"]  # type: ignore

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.NONE
        self.organization.save()
        response = self.client.post(
            "/api/plugin_config/",
            {"plugin": plugin_id, "enabled": True, "order": 0, "config": json.dumps({"bar": "moop"})},
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
            )
            self.assertEqual(response.status_code, 201)

    def test_update_plugin_config_auth(self, mock_get, mock_reload):
        response = self.client.post(
            "/api/organizations/@current/plugins/", {"url": "https://github.com/PostHog/helloworldplugin"}
        )
        plugin_id = response.data["id"]  # type: ignore
        response = self.client.post(
            "/api/plugin_config/",
            {"plugin": plugin_id, "enabled": True, "order": 0, "config": json.dumps({"bar": "moop"})},
        )
        plugin_config_id = response.data["id"]  # type: ignore

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
            )
            self.assertEqual(response.status_code, 200)

        self.organization.plugins_access_level = Organization.PluginsAccessLevel.NONE
        self.organization.save()
        response = self.client.patch(
            "/api/plugin_config/{}".format(plugin_config_id),
            {"enabled": False, "order": 1, "config": json.dumps({"bar": "soup"})},
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_plugin_config_auth(self, mock_get, mock_reload):
        response = self.client.post(
            "/api/organizations/@current/plugins/", {"url": "https://github.com/PostHog/helloworldplugin"}
        )
        plugin_id = response.data["id"]  # type: ignore
        response = self.client.post(
            "/api/plugin_config/",
            {"plugin": plugin_id, "enabled": True, "order": 0, "config": json.dumps({"bar": "moop"})},
        )
        plugin_config_id = response.data["id"]  # type: ignore

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
        plugin_id = response.data["id"]  # type: ignore
        response = self.client.post(
            "/api/plugin_config/",
            {
                "plugin": plugin_id,
                "enabled": True,
                "order": 0,
                "config": json.dumps({"bar": "moop"}),
                "add_attachment[foodb]": tmp_file_1,
            },
        )
        plugin_config_id = response.data["id"]  # type: ignore
        plugin_attachment_id = response.data["config"]["foodb"]["uid"]  # type: ignore

        response = self.client.get("/api/plugin_config/{}".format(plugin_config_id))
        self.assertEqual(
            response.data["config"],  # type: ignore
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
            response.data["config"],  # type: ignore
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
        self.assertEqual(response.data["config"], {"bar": "moop"})  # type: ignore
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
        plugin_id = response.data["id"]  # type: ignore
        response = self.client.post(
            "/api/plugin_config/",
            {"plugin": plugin_id, "enabled": True, "order": 0, "config": json.dumps({"bar": "very secret value"})},
        )
        plugin_config_id = response.data["id"]  # type: ignore
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginConfig.objects.count(), 1)

        self.assertEqual(
            response.data,
            {
                "id": plugin_config_id,
                "plugin": plugin_id,
                "enabled": True,
                "order": 0,
                "config": {"bar": "**************** POSTHOG SECRET FIELD ****************"},
                "error": None,
            },
        )

        # Test a config change and that an empty config is returned to the client instead of the secret placeholder
        response = self.client.patch(
            "/api/plugin_config/{}".format(plugin_config_id),
            {"enabled": False, "order": 1, "config": json.dumps({"bar": ""})},
        )
        plugin_config_id = response.data["id"]  # type: ignore
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginConfig.objects.count(), 1)
        self.assertEqual(
            response.data,
            {
                "id": plugin_config_id,
                "plugin": plugin_id,
                "enabled": False,
                "order": 1,
                "config": {"bar": ""},  # empty secret configs are returned normally
                "error": None,
            },
        )

        # Test that secret values are updated but never revealed
        response = self.client.patch(
            "/api/plugin_config/{}".format(plugin_config_id),
            {"enabled": False, "order": 1, "config": json.dumps({"bar": "a new very secret value"})},
        )
        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(
            response.data,
            {
                "id": plugin_config_id,
                "plugin": plugin_id,
                "enabled": False,
                "order": 1,
                "config": {"bar": "**************** POSTHOG SECRET FIELD ****************"},
                "error": None,
            },
        )
        plugin_config = PluginConfig.objects.get(plugin=plugin_id)
        self.assertEqual(plugin_config.config, {"bar": "a new very secret value"})
