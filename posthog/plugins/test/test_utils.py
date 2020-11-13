import base64
from unittest import mock

from posthog.api.test.base import BaseTest
from posthog.plugins.utils import download_plugin_archive, get_json_from_archive, parse_url

from .plugin_archives import HELLO_WORLD_PLUGIN_GITHUB_ZIP, HELLO_WORLD_PLUGIN_NPM_TGZ


# This method will be used by the mock to replace requests.get
def mocked_requests_get(*args, **kwargs):
    class MockJSONResponse:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

        def ok(self):
            return self.status_code < 300

    class MockBase64Response:
        def __init__(self, base64_data, status_code):
            self.content = base64.b64decode(base64_data)
            self.status_code = status_code

        def ok(self):
            return self.status_code < 300

    if args[0] == "https://api.github.com/repos/PostHog/posthog/commits":
        return MockJSONResponse([{"html_url": "https://www.github.com/PostHog/posthog/commit/MOCKLATESTCOMMIT"}], 200)

    if args[0] == "https://registry.npmjs.org/posthog-helloworld-plugin/latest":
        return MockJSONResponse({"pkg": "posthog-helloworld-plkugin", "version": "MOCK"}, 200)

    if args[0] == "https://github.com/PostHog/helloworldplugin/archive/{}.zip".format(HELLO_WORLD_PLUGIN_GITHUB_ZIP[0]):
        return MockBase64Response(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1], 200)

    if args[0] == "https://registry.npmjs.org/posthog-helloworld-plugin/-/posthog-helloworld-plugin-0.0.0.tgz":
        return MockBase64Response(HELLO_WORLD_PLUGIN_NPM_TGZ[1], 200)

    return MockJSONResponse(None, 404)


@mock.patch("requests.get", side_effect=mocked_requests_get)
class TestPluginsUtils(BaseTest):
    def test_parse_urls(self, mock_get):
        parsed_url = parse_url("https://github.com/PostHog/posthog")
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url.get("tag", None), None)

        parsed_url = parse_url("https://github.com/PostHog/posthog", get_latest_if_none=True)
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "MOCKLATESTCOMMIT")

        parsed_url = parse_url("https://github.com/PostHog/posthog/tree/82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")

        parsed_url = parse_url(
            "https://github.com/PostHog/posthog/tree/82c9218ee40f561b7f37a22d6b6a0ca82887ee3e", get_latest_if_none=True
        )
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")

        parsed_url = parse_url("https://www.github.com/PostHog/posthog/commit/82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")

        parsed_url = parse_url(
            "https://github.com/PostHog/posthog/releases/tag/82c9218ee40f561b7f37a22d6b6a0ca82887ee3e"
        )
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")

        parsed_url = parse_url(
            "https://www.github.com/PostHog/posthog/archive/82c9218ee40f561b7f37a22d6b6a0ca82887ee3e.zip"
        )
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")

        parsed_url = parse_url(
            "https://github.com/PostHog/posthog/archive/82c9218ee40f561b7f37a22d6b6a0ca82887ee3e.tar.gz"
        )
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")

        parsed_url = parse_url("https://www.npmjs.com/package/posthog-helloworld-plugin")
        self.assertEqual(parsed_url["type"], "npm")
        self.assertEqual(parsed_url["pkg"], "posthog-helloworld-plugin")
        self.assertEqual(parsed_url.get("version", None), None)

        parsed_url = parse_url("https://www.npmjs.com/package/posthog-helloworld-plugin", get_latest_if_none=True)
        self.assertEqual(parsed_url["type"], "npm")
        self.assertEqual(parsed_url["pkg"], "posthog-helloworld-plugin")
        self.assertEqual(parsed_url["version"], "MOCK")

        parsed_url = parse_url("https://www.npmjs.com/package/posthog-helloworld-plugin/v/0.0.0")
        self.assertEqual(parsed_url["type"], "npm")
        self.assertEqual(parsed_url["pkg"], "posthog-helloworld-plugin")
        self.assertEqual(parsed_url["version"], "0.0.0")

        parsed_url = parse_url(
            "https://www.npmjs.com/package/posthog-helloworld-plugin/v/0.0.0", get_latest_if_none=True
        )
        self.assertEqual(parsed_url["type"], "npm")
        self.assertEqual(parsed_url["pkg"], "posthog-helloworld-plugin")
        self.assertEqual(parsed_url["version"], "0.0.0")

    def test_download_plugin_archive(self, mock_get):
        plugin_github_zip_1 = download_plugin_archive(
            "https://www.github.com/PostHog/helloworldplugin/commit/82c9218ee40f561b7f37a22d6b6a0ca82887ee3e",
            HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
        )
        self.assertEqual(plugin_github_zip_1, base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]))

        plugin_github_zip_2 = download_plugin_archive(
            "https://www.github.com/PostHog/helloworldplugin/commit/{}".format(HELLO_WORLD_PLUGIN_GITHUB_ZIP[0])
        )
        self.assertEqual(plugin_github_zip_2, base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]))

        plugin_npm_tgz = download_plugin_archive("https://www.npmjs.com/package/posthog-helloworld-plugin/v/0.0.0")
        self.assertEqual(plugin_npm_tgz, base64.b64decode(HELLO_WORLD_PLUGIN_NPM_TGZ[1]))

    def test_get_json_from_archive(self, mock_get):
        plugin_json_zip = get_json_from_archive(base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]), "plugin.json")
        self.assertEqual(plugin_json_zip["name"], "helloworldplugin")
        self.assertEqual(plugin_json_zip["url"], "https://github.com/PostHog/helloworldplugin")
        self.assertEqual(plugin_json_zip["description"], "Greet the World and Foo a Bar")

        plugin_json_tgz = get_json_from_archive(base64.b64decode(HELLO_WORLD_PLUGIN_NPM_TGZ[1]), "plugin.json")
        self.assertEqual(plugin_json_tgz["name"], "helloworldplugin")
        self.assertEqual(plugin_json_tgz["url"], "https://github.com/PostHog/helloworldplugin")
        self.assertEqual(plugin_json_tgz["description"], "Greet the World and Foo a Bar, JS edition!")
