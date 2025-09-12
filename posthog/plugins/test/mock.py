import json
import base64
from typing import cast

# This method will be used by the mock to replace requests.get
from posthog.plugins.utils import get_file_from_zip_archive, put_json_into_zip_archive

from .plugin_archives import (
    HELLO_WORLD_PLUGIN_GITHUB_ATTACHMENT_ZIP,
    HELLO_WORLD_PLUGIN_GITHUB_SUBDIR_ZIP,
    HELLO_WORLD_PLUGIN_GITHUB_ZIP,
    HELLO_WORLD_PLUGIN_GITLAB_ZIP,
    HELLO_WORLD_PLUGIN_NPM_TGZ,
    HELLO_WORLD_PLUGIN_SECRET_GITHUB_ZIP,
)


def mocked_plugin_requests_get(*args, **kwargs):
    class MockJSONResponse:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

        def ok(self):
            return self.status_code < 300

    class MockTextResponse:
        def __init__(self, text, status_code):
            self.text = text
            self.status_code = status_code

        def ok(self):
            return self.status_code < 300

    class MockBase64Response:
        def __init__(self, base64_data, status_code):
            self.content = base64.b64decode(base64_data)
            self.status_code = status_code

        def ok(self):
            return self.status_code < 300

    if args[0] == "https://api.github.com/repos/PostHog/posthog/commits?sha=&path=":
        return MockJSONResponse(
            [
                {
                    "sha": "MOCKLATESTCOMMIT",
                    "html_url": "https://www.github.com/PostHog/posthog/commit/MOCKLATESTCOMMIT",
                }
            ],
            200,
        )

    if args[0] == "https://api.github.com/repos/PostHog/posthog/commits?sha=main&path=":
        return MockJSONResponse(
            [
                {
                    "sha": "MOCKLATESTCOMMIT",
                    "html_url": "https://www.github.com/PostHog/posthog/commit/MOCKLATESTCOMMIT",
                }
            ],
            200,
        )

    if args[0] == "https://api.github.com/repos/PostHog/posthog/commits?sha=main&path=test/path/in/repo":
        return MockJSONResponse(
            [
                {
                    "sha": "MOCKLATESTCOMMIT",
                    "html_url": "https://www.github.com/PostHog/posthog/commit/MOCKLATESTCOMMIT",
                }
            ],
            200,
        )

    if args[0] == "https://api.github.com/repos/PostHog/helloworldplugin/commits?sha=&path=":
        return MockJSONResponse(
            [
                {
                    "sha": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                    "html_url": "https://www.github.com/PostHog/helloworldplugin/commit/{}".format(
                        HELLO_WORLD_PLUGIN_GITHUB_ZIP[0]
                    ),
                }
            ],
            200,
        )

    if args[0] == "https://api.github.com/repos/PostHog/helloworldplugin/commits?sha=main&path=":
        return MockJSONResponse(
            {"commit": {"sha": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0]}},
            200,
        )

    if args[0].startswith("https://gitlab.com/api/v4/projects/mariusandra%2Fhelloworldplugin/repository/commits"):
        return MockJSONResponse(
            [
                {
                    "id": "ff78cbe1d70316055c610a962a8355a4616d874b",
                    "web_url": "https://gitlab.com/mariusandra/helloworldplugin/-/commit/ff78cbe1d70316055c610a962a8355a4616d874b",
                }
            ],
            200,
        )

    if args[0].startswith("https://gitlab.com/api/v4/projects/mariusandra%2Fhelloworldplugin-other/repository/commits"):
        return MockJSONResponse(
            [
                {
                    "id": "ff78cbe1d70316055c610a962a8355a4616d874b",
                    "web_url": "https://gitlab.com/mariusandra/helloworldplugin-other/-/commit/ff78cbe1d70316055c610a962a8355a4616d874b",
                }
            ],
            200,
        )

    if args[0] == "https://registry.npmjs.org/posthog-helloworld-plugin/latest":
        return MockJSONResponse({"pkg": "posthog-helloworld-plugin", "version": "MOCK"}, 200)

    if args[0] == "https://registry.npmjs.org/@posthog/helloworldplugin/latest":
        return MockJSONResponse({"pkg": "@posthog/helloworldplugin", "version": "MOCK"}, 200)

    if args[0] == "https://github.com/PostHog/helloworldplugin/archive/{}.zip".format(HELLO_WORLD_PLUGIN_GITHUB_ZIP[0]):
        return MockBase64Response(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1], 200)

    if args[0] == "https://github.com/PostHog/helloworldplugin/archive/{}.zip".format(
        HELLO_WORLD_PLUGIN_GITHUB_ATTACHMENT_ZIP[0]
    ):
        return MockBase64Response(HELLO_WORLD_PLUGIN_GITHUB_ATTACHMENT_ZIP[1], 200)

    if args[0] == "https://github.com/PostHog/helloworldplugin/archive/{}.zip".format(
        HELLO_WORLD_PLUGIN_SECRET_GITHUB_ZIP[0]
    ):
        return MockBase64Response(HELLO_WORLD_PLUGIN_SECRET_GITHUB_ZIP[1], 200)

    if args[0] == "https://github.com/PostHog/helloworldplugin/archive/{}.zip".format(
        HELLO_WORLD_PLUGIN_GITHUB_SUBDIR_ZIP[0]
    ):
        return MockBase64Response(HELLO_WORLD_PLUGIN_GITHUB_SUBDIR_ZIP[1], 200)

    # https://github.com/posthog-plugin/version-equals/commit/{vesrion}
    # https://github.com/posthog-plugin/version-greater-than/commit/{vesrion}
    # https://github.com/posthog-plugin/version-less-than/commit/{vesrion}
    if args[0].startswith(f"https://github.com/posthog-plugin/version-"):
        url_repo = args[0].split("/")[4]
        url_version = args[0].split("/")[6].split(".zip")[0]

        archive = base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1])
        plugin_json = cast(dict, get_file_from_zip_archive(archive, "plugin.json", json_parse=True))
        plugin_json["posthogVersion"] = url_version

        if url_repo == "version-greater-than":
            plugin_json["posthogVersion"] = f">= {plugin_json['posthogVersion']}"

        if url_repo == "version-less-than":
            plugin_json["posthogVersion"] = f"< {plugin_json['posthogVersion']}"

        archive = put_json_into_zip_archive(archive, plugin_json, "plugin.json")
        return MockBase64Response(base64.b64encode(archive), 200)

    if args[0].startswith(
        "https://gitlab.com/api/v4/projects/mariusandra%2Fhelloworldplugin/repository/archive.zip?sha={}".format(
            HELLO_WORLD_PLUGIN_GITLAB_ZIP[0]
        )
    ) or args[0].startswith(
        "https://gitlab.com/api/v4/projects/mariusandra%2Fhelloworldplugin-other/repository/archive.zip?sha={}".format(
            HELLO_WORLD_PLUGIN_GITLAB_ZIP[0]
        )
    ):
        return MockBase64Response(HELLO_WORLD_PLUGIN_GITLAB_ZIP[1], 200)

    if args[0] == "https://registry.npmjs.org/@posthog/helloworldplugin/-/helloworldplugin-0.0.0.tgz":
        return MockBase64Response(HELLO_WORLD_PLUGIN_NPM_TGZ[1], 200)

    if args[0] == "https://registry.npmjs.org/posthog-helloworld-plugin/-/posthog-helloworld-plugin-0.0.0.tgz":
        return MockBase64Response(HELLO_WORLD_PLUGIN_NPM_TGZ[1], 200)

    if args[0] == "https://raw.githubusercontent.com/PostHog/integrations-repository/main/plugins.json":
        return MockTextResponse(
            json.dumps(
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
                ]
            ),
            200,
        )

    return MockJSONResponse(None, 404)
