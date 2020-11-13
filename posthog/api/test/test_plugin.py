from unittest import mock

from posthog.models import Plugin
from posthog.plugins.test.mock import mocked_plugin_requests_get
from posthog.plugins.test.plugin_archives import HELLO_WORLD_PLUGIN_GITHUB_OTHER_ZIP, HELLO_WORLD_PLUGIN_GITHUB_ZIP

from .base import APIBaseTest


def mocked_plugin_reload(*args, **kwargs):
    pass


@mock.patch("posthog.api.plugin.reload_plugins_on_workers", side_effect=mocked_plugin_reload)
@mock.patch("requests.get", side_effect=mocked_plugin_requests_get)
class TestPluginAPI(APIBaseTest):
    def test_create_plugin_auth(self, mock_get, mock_reload):
        repo_url = "https://github.com/PostHog/helloworldplugin"
        with self.settings(PLUGINS_INSTALL_VIA_API=False, PLUGINS_CONFIGURE_VIA_API=False):
            response = self.client.post("/api/plugin/", {"url": repo_url})
            self.assertEqual(response.status_code, 400)
        with self.settings(PLUGINS_INSTALL_VIA_API=False, PLUGINS_CONFIGURE_VIA_API=True):
            response = self.client.post("/api/plugin/", {"url": repo_url})
            self.assertEqual(response.status_code, 400)
        with self.settings(PLUGINS_INSTALL_VIA_API=True, PLUGINS_CONFIGURE_VIA_API=False):
            response = self.client.post("/api/plugin/", {"url": repo_url})
            self.assertEqual(response.status_code, 201)
        with self.settings(PLUGINS_INSTALL_VIA_API=True, PLUGINS_CONFIGURE_VIA_API=True):
            response = self.client.post("/api/plugin/", {"url": repo_url})
            self.assertEqual(response.status_code, 400)  # already installed, tested separately below

    def test_update_plugin_auth(self, mock_get, mock_reload):
        repo_url = "https://github.com/PostHog/helloworldplugin"
        with self.settings(PLUGINS_INSTALL_VIA_API=True, PLUGINS_CONFIGURE_VIA_API=True):
            response = self.client.post("/api/plugin/", {"url": repo_url})
            self.assertEqual(response.status_code, 201)
        api_url = "/api/plugin/{}".format(response.data["id"])
        with self.settings(PLUGINS_INSTALL_VIA_API=True, PLUGINS_CONFIGURE_VIA_API=True):
            response = self.client.patch(api_url, {"url": repo_url})
            self.assertEqual(response.status_code, 200)
        with self.settings(PLUGINS_INSTALL_VIA_API=False, PLUGINS_CONFIGURE_VIA_API=False):
            response = self.client.patch(api_url, {"url": repo_url})
            self.assertEqual(response.status_code, 404)
        with self.settings(PLUGINS_INSTALL_VIA_API=False, PLUGINS_CONFIGURE_VIA_API=True):
            response = self.client.patch(api_url, {"url": repo_url})
            self.assertEqual(response.status_code, 404)
        with self.settings(PLUGINS_INSTALL_VIA_API=True, PLUGINS_CONFIGURE_VIA_API=False):
            response = self.client.patch(api_url, {"url": repo_url})
            self.assertEqual(response.status_code, 200)

    def test_delete_plugin_auth(self, mock_get, mock_reload):
        repo_url = "https://github.com/PostHog/helloworldplugin"
        with self.settings(PLUGINS_INSTALL_VIA_API=True, PLUGINS_CONFIGURE_VIA_API=True):
            response = self.client.post("/api/plugin/", {"url": repo_url})
            self.assertEqual(response.status_code, 201)
        api_url = "/api/plugin/{}".format(response.data["id"])

        with self.settings(PLUGINS_INSTALL_VIA_API=False, PLUGINS_CONFIGURE_VIA_API=False):
            response = self.client.delete(api_url)
            self.assertEqual(response.status_code, 404)
        with self.settings(PLUGINS_INSTALL_VIA_API=False, PLUGINS_CONFIGURE_VIA_API=True):
            response = self.client.delete(api_url)
            self.assertEqual(response.status_code, 404)

        with self.settings(PLUGINS_INSTALL_VIA_API=True, PLUGINS_CONFIGURE_VIA_API=True):
            response = self.client.delete(api_url)
            self.assertEqual(response.status_code, 204)

        with self.settings(PLUGINS_INSTALL_VIA_API=True, PLUGINS_CONFIGURE_VIA_API=True):  # create again
            response = self.client.post("/api/plugin/", {"url": repo_url})
            self.assertEqual(response.status_code, 201)
        api_url = "/api/plugin/{}".format(response.data["id"])
        with self.settings(PLUGINS_INSTALL_VIA_API=True, PLUGINS_CONFIGURE_VIA_API=False):
            response = self.client.delete(api_url)
            self.assertEqual(response.status_code, 204)

    def test_create_plugin_repo_url(self, mock_get, mock_reload):
        with self.settings(PLUGINS_INSTALL_VIA_API=True, PLUGINS_CONFIGURE_VIA_API=True):
            self.assertEqual(mock_reload.call_count, 0)
            response = self.client.post("/api/plugin/", {"url": "https://github.com/PostHog/helloworldplugin"})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(
                response.data,
                {
                    "id": response.data["id"],  # type: ignore
                    "name": "helloworldplugin",
                    "description": "Greet the World and Foo a Bar, JS edition!",
                    "url": "https://github.com/PostHog/helloworldplugin",
                    "config_schema": {
                        "bar": {"name": "What's in the bar?", "type": "string", "default": "baz", "required": False,},
                    },
                    "tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                    "error": None,
                    "from_json": False,
                },
            )
            self.assertEqual(Plugin.objects.count(), 1)
            self.assertEqual(mock_reload.call_count, 1)

        with self.settings(PLUGINS_INSTALL_VIA_API=True, PLUGINS_CONFIGURE_VIA_API=True):
            self.client.delete("/api/plugin/{}".format(response.data["id"]))  # type: ignore
            self.assertEqual(Plugin.objects.count(), 0)
            self.assertEqual(mock_reload.call_count, 2)

    def test_create_plugin_commit_url(self, mock_get, mock_reload):
        with self.settings(PLUGINS_INSTALL_VIA_API=True):
            self.assertEqual(mock_reload.call_count, 0)
            response = self.client.post(
                "/api/plugin/",
                {
                    "url": "https://github.com/PostHog/helloworldplugin/commit/{}".format(
                        HELLO_WORLD_PLUGIN_GITHUB_ZIP[0]
                    )
                },
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(
                response.data,
                {
                    "id": response.data["id"],  # type: ignore
                    "name": "helloworldplugin",
                    "description": "Greet the World and Foo a Bar, JS edition!",
                    "url": "https://github.com/PostHog/helloworldplugin",
                    "config_schema": {
                        "bar": {"name": "What's in the bar?", "type": "string", "default": "baz", "required": False,},
                    },
                    "tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                    "error": None,
                    "from_json": False,
                },
            )
            self.assertEqual(Plugin.objects.count(), 1)
            self.assertEqual(mock_reload.call_count, 1)

            response2 = self.client.patch(
                "/api/plugin/{}".format(response.data["id"]),  # type: ignore
                {
                    "url": "https://github.com/PostHog/helloworldplugin/commit/{}".format(
                        HELLO_WORLD_PLUGIN_GITHUB_OTHER_ZIP[0]
                    )
                },
            )
            self.assertEqual(response2.status_code, 200)
            self.assertEqual(
                response2.data,
                {
                    "id": response.data["id"],  # type: ignore
                    "name": "helloworldplugin",
                    "description": "Greet the World and Foo a Bar, JS edition, vol 2!",
                    "url": "https://github.com/PostHog/helloworldplugin",
                    "config_schema": {
                        "bar": {"name": "What's in the bar?", "type": "string", "default": "baz", "required": False,},
                    },
                    "tag": HELLO_WORLD_PLUGIN_GITHUB_OTHER_ZIP[0],
                    "error": None,
                    "from_json": False,
                },
            )
            self.assertEqual(Plugin.objects.count(), 1)
            self.assertEqual(mock_reload.call_count, 2)
