from unittest import mock

from posthog.models import Plugin
from posthog.plugins.test.mock import mocked_plugin_requests_get
from posthog.plugins.test.plugin_archives import HELLO_WORLD_PLUGIN_GITHUB_ZIP

from .base import APIBaseTest


@mock.patch("requests.get", side_effect=mocked_plugin_requests_get)
class TestPluginAPI(APIBaseTest):
    def test_create_plugin_repo_url(self, mock_get):
        with self.settings(MULTI_TENANCY=False):
            response = self.client.post("/api/plugin/", {"url": "https://github.com/PostHog/helloworldplugin"})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(
                response.data,
                {
                    "id": response.data["id"],
                    "name": "helloworldplugin",
                    "description": "Greet the World and Foo a Bar",
                    "url": "https://github.com/PostHog/helloworldplugin",
                    "config_schema": {
                        "bar": {"name": "What's in the bar?", "type": "string", "default": "baz", "required": False,},
                    },
                    "tag": "3c4c77e7d7878e87be3c2373b658c74ec3085f49",
                    "error": None,
                    "from_json": False,
                },
            )
            self.assertEqual(Plugin.objects.count(), 1)

    def test_create_plugin_commit_url(self, mock_get):
        with self.settings(MULTI_TENANCY=False):
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
                    "id": response.data["id"],
                    "name": "helloworldplugin",
                    "description": "Greet the World and Foo a Bar",
                    "url": "https://github.com/PostHog/helloworldplugin",
                    "config_schema": {
                        "bar": {"name": "What's in the bar?", "type": "string", "default": "baz", "required": False,},
                    },
                    "tag": "3c4c77e7d7878e87be3c2373b658c74ec3085f49",
                    "error": None,
                    "from_json": False,
                },
            )
            self.assertEqual(Plugin.objects.count(), 1)
