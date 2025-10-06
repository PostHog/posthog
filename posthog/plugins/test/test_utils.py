import io
import base64
from typing import cast
from zipfile import ZipFile

from posthog.test.base import BaseTest
from unittest import mock

from posthog.plugins.utils import (
    download_plugin_archive,
    get_file_from_archive,
    get_file_from_zip_archive,
    parse_url,
    put_json_into_zip_archive,
)

from .mock import mocked_plugin_requests_get
from .plugin_archives import (
    HELLO_WORLD_PLUGIN_GITHUB_SUBDIR_ZIP,
    HELLO_WORLD_PLUGIN_GITHUB_ZIP,
    HELLO_WORLD_PLUGIN_GITLAB_ZIP,
    HELLO_WORLD_PLUGIN_NPM_TGZ,
)


@mock.patch("requests.get", side_effect=mocked_plugin_requests_get)
class TestPluginsUtils(BaseTest):
    def test_parse_github_urls(self, mock_get):
        parsed_url = parse_url("https://github.com/PostHog/posthog")
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url.get("tag", None), None)
        self.assertEqual(parsed_url.get("path", None), None)
        self.assertEqual(mock_get.call_count, 0)
        mock_get.reset_mock()

        parsed_url = parse_url("https://github.com/PostHog/posthog", get_latest_if_none=True)
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "MOCKLATESTCOMMIT")
        self.assertEqual(parsed_url.get("path", None), None)
        self.assertEqual(mock_get.call_count, 1)
        mock_get.assert_called_with(
            "https://api.github.com/repos/PostHog/posthog/commits?sha=&path=",
            headers={},
        )
        mock_get.reset_mock()

        parsed_url = parse_url("https://github.com/PostHog/posthog/tree/82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")
        self.assertEqual(parsed_url.get("path", None), None)
        self.assertEqual(mock_get.call_count, 0)
        mock_get.reset_mock()

        parsed_url = parse_url(
            "https://github.com/PostHog/posthog/tree/82c9218ee40f561b7f37a22d6b6a0ca82887ee3e",
            get_latest_if_none=True,
        )
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")
        self.assertEqual(parsed_url.get("path", None), None)
        self.assertEqual(mock_get.call_count, 0)
        mock_get.reset_mock()

        parsed_url = parse_url(
            "https://github.com/PostHog/posthog/tree/82c9218ee40f561b7f37a22d6b6a0ca82887ee3e/test/path/in/repo",
            get_latest_if_none=True,
        )
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")
        self.assertEqual(parsed_url["path"], "test/path/in/repo")
        self.assertEqual(mock_get.call_count, 0)
        mock_get.reset_mock()

        parsed_url = parse_url("https://github.com/PostHog/posthog/tree/main", get_latest_if_none=True)
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "MOCKLATESTCOMMIT")
        self.assertEqual(parsed_url.get("path", None), None)
        self.assertEqual(mock_get.call_count, 1)
        mock_get.assert_called_with(
            "https://api.github.com/repos/PostHog/posthog/commits?sha=main&path=",
            headers={},
        )
        mock_get.reset_mock()

        parsed_url = parse_url(
            "https://github.com/PostHog/posthog/tree/main/test/path/in/repo",
            get_latest_if_none=True,
        )
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "MOCKLATESTCOMMIT")
        self.assertEqual(parsed_url["path"], "test/path/in/repo")
        self.assertEqual(mock_get.call_count, 1)
        mock_get.assert_called_with(
            "https://api.github.com/repos/PostHog/posthog/commits?sha=main&path=test/path/in/repo",
            headers={},
        )
        mock_get.reset_mock()

        parsed_url = parse_url("https://www.github.com/PostHog/posthog/commit/82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")
        self.assertEqual(parsed_url.get("path", None), None)
        self.assertEqual(mock_get.call_count, 0)
        mock_get.reset_mock()

        parsed_url = parse_url(
            "https://www.github.com/PostHog/posthog/commit/82c9218ee40f561b7f37a22d6b6a0ca82887ee3e",
            get_latest_if_none=True,
        )
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")
        self.assertEqual(parsed_url.get("path", None), None)
        self.assertEqual(mock_get.call_count, 0)
        mock_get.reset_mock()

        parsed_url = parse_url(
            "https://github.com/PostHog/posthog/releases/tag/82c9218ee40f561b7f37a22d6b6a0ca82887ee3e"
        )
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")
        self.assertEqual(parsed_url.get("path", None), None)
        self.assertEqual(mock_get.call_count, 0)
        mock_get.reset_mock()

        parsed_url = parse_url(
            "https://www.github.com/PostHog/posthog/archive/82c9218ee40f561b7f37a22d6b6a0ca82887ee3e.zip"
        )
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")
        self.assertEqual(parsed_url.get("path", None), None)
        self.assertEqual(mock_get.call_count, 0)
        mock_get.reset_mock()

        parsed_url = parse_url(
            "https://github.com/PostHog/posthog/archive/82c9218ee40f561b7f37a22d6b6a0ca82887ee3e.tar.gz"
        )
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")
        self.assertEqual(parsed_url.get("path", None), None)
        self.assertEqual(mock_get.call_count, 0)
        mock_get.reset_mock()

        # private tokens
        parsed_url = parse_url("https://github.com/PostHog/posthog?private_token=TOKEN")
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url.get("tag", None), None)
        self.assertEqual(parsed_url.get("path", None), None)
        self.assertEqual(parsed_url["private_token"], "TOKEN")
        self.assertEqual(mock_get.call_count, 0)
        mock_get.reset_mock()

        parsed_url = parse_url(
            "https://github.com/PostHog/posthog?private_token=TOKEN",
            get_latest_if_none=True,
        )
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "MOCKLATESTCOMMIT")
        self.assertEqual(parsed_url.get("path", None), None)
        mock_get.assert_called_with(
            "https://api.github.com/repos/PostHog/posthog/commits?sha=&path=",
            headers={"Authorization": "Bearer TOKEN"},
        )
        self.assertEqual(mock_get.call_count, 1)
        mock_get.reset_mock()

        parsed_url = parse_url(
            "https://github.com/PostHog/posthog/tree/82c9218ee40f561b7f37a22d6b6a0ca82887ee3e?private_token=TOKEN"
        )
        self.assertEqual(parsed_url["type"], "github")
        self.assertEqual(parsed_url["user"], "PostHog")
        self.assertEqual(parsed_url["repo"], "posthog")
        self.assertEqual(parsed_url["tag"], "82c9218ee40f561b7f37a22d6b6a0ca82887ee3e")
        self.assertEqual(parsed_url.get("path", None), None)
        self.assertEqual(parsed_url["private_token"], "TOKEN")
        self.assertEqual(mock_get.call_count, 0)
        mock_get.reset_mock()

        # default global token
        with self.settings(GITHUB_TOKEN="MY_GITHUB_TOKEN"):
            parsed_url = parse_url("https://github.com/PostHog/posthog", get_latest_if_none=True)
            self.assertEqual(parsed_url["type"], "github")
            self.assertEqual(parsed_url["user"], "PostHog")
            self.assertEqual(parsed_url["repo"], "posthog")
            self.assertEqual(parsed_url["tag"], "MOCKLATESTCOMMIT")
            self.assertEqual(parsed_url.get("path", None), None)
            self.assertEqual(parsed_url.get("private_token", None), None)
            mock_get.assert_called_with(
                "https://api.github.com/repos/PostHog/posthog/commits?sha=&path=",
                headers={"Authorization": "Bearer MY_GITHUB_TOKEN"},
            )
            self.assertEqual(mock_get.call_count, 1)
            mock_get.reset_mock()

            parsed_url = parse_url(
                "https://github.com/PostHog/posthog?private_token=TOKEN",
                get_latest_if_none=True,
            )
            self.assertEqual(parsed_url["type"], "github")
            self.assertEqual(parsed_url["user"], "PostHog")
            self.assertEqual(parsed_url["repo"], "posthog")
            self.assertEqual(parsed_url["tag"], "MOCKLATESTCOMMIT")
            self.assertEqual(parsed_url.get("path", None), None)
            self.assertEqual(parsed_url["private_token"], "TOKEN")
            mock_get.assert_called_with(
                "https://api.github.com/repos/PostHog/posthog/commits?sha=&path=",
                headers={"Authorization": "Bearer TOKEN"},
            )
            self.assertEqual(mock_get.call_count, 1)
            mock_get.reset_mock()

    def test_parse_gitlab_urls(self, mock_get):
        parsed_url = parse_url("https://gitlab.com/mariusandra/helloworldplugin")
        self.assertEqual(parsed_url["type"], "gitlab")
        self.assertEqual(parsed_url["project"], "mariusandra/helloworldplugin")
        self.assertEqual(parsed_url.get("tag", None), None)
        self.assertEqual(mock_get.call_count, 0)

        parsed_url = parse_url("https://gitlab.com/mariusandra/helloworldplugin", get_latest_if_none=True)
        self.assertEqual(parsed_url["type"], "gitlab")
        self.assertEqual(parsed_url["project"], "mariusandra/helloworldplugin")
        self.assertEqual(parsed_url["tag"], "ff78cbe1d70316055c610a962a8355a4616d874b")
        self.assertEqual(parsed_url.get("private_token", None), None)
        self.assertEqual(mock_get.call_count, 1)
        mock_get.assert_called_with(
            "https://gitlab.com/api/v4/projects/mariusandra%2Fhelloworldplugin/repository/commits",
            headers={},
        )

        parsed_url = parse_url(
            "https://gitlab.com/gitlab-org/gl-openshift/openshift-demos/openshift-custom-pipeline/-/tree/master"
        )
        self.assertEqual(
            parsed_url["project"],
            "gitlab-org/gl-openshift/openshift-demos/openshift-custom-pipeline",
        )
        self.assertEqual(parsed_url["tag"], "master")
        self.assertEqual(mock_get.call_count, 1)

        parsed_url = parse_url(
            "https://gitlab.com/gitlab-org/gl-openshift/openshift-demos/openshift-custom-pipeline/-/tree/2b6494bdf8ad35073aafe36ca8a1bdfaf3dc72d1"
        )
        self.assertEqual(
            parsed_url["project"],
            "gitlab-org/gl-openshift/openshift-demos/openshift-custom-pipeline",
        )
        self.assertEqual(parsed_url["tag"], "2b6494bdf8ad35073aafe36ca8a1bdfaf3dc72d1")
        self.assertEqual(mock_get.call_count, 1)

        parsed_url = parse_url(
            "https://gitlab.com/gitlab-org/gl-openshift/openshift-demos/openshift-custom-pipeline/-/commit/2b6494bdf8ad35073aafe36ca8a1bdfaf3dc72d1"
        )
        self.assertEqual(
            parsed_url["project"],
            "gitlab-org/gl-openshift/openshift-demos/openshift-custom-pipeline",
        )
        self.assertEqual(parsed_url["tag"], "2b6494bdf8ad35073aafe36ca8a1bdfaf3dc72d1")
        self.assertEqual(mock_get.call_count, 1)

        parsed_url = parse_url(
            "https://gitlab.com/gitlab-org/gl-openshift/openshift-demos/openshift-custom-pipeline/-/archive/master/openshift-custom-pipeline-master.zip"
        )
        self.assertEqual(
            parsed_url["project"],
            "gitlab-org/gl-openshift/openshift-demos/openshift-custom-pipeline",
        )
        self.assertEqual(parsed_url["tag"], "master")
        self.assertEqual(mock_get.call_count, 1)

        # private tokens
        parsed_url = parse_url("https://gitlab.com/mariusandra/helloworldplugin?private_token=PRIVATE")
        self.assertEqual(parsed_url["type"], "gitlab")
        self.assertEqual(parsed_url["project"], "mariusandra/helloworldplugin")
        self.assertEqual(parsed_url.get("tag", None), None)
        self.assertEqual(parsed_url["private_token"], "PRIVATE")
        self.assertEqual(mock_get.call_count, 1)

        parsed_url = parse_url(
            "https://gitlab.com/mariusandra/helloworldplugin?private_token=PRIVATE",
            get_latest_if_none=True,
        )
        self.assertEqual(parsed_url["type"], "gitlab")
        self.assertEqual(parsed_url["project"], "mariusandra/helloworldplugin")
        self.assertEqual(parsed_url["tag"], "ff78cbe1d70316055c610a962a8355a4616d874b")
        self.assertEqual(parsed_url["private_token"], "PRIVATE")
        self.assertEqual(mock_get.call_count, 2)
        mock_get.assert_called_with(
            "https://gitlab.com/api/v4/projects/mariusandra%2Fhelloworldplugin/repository/commits",
            headers={"Authorization": "Bearer PRIVATE"},
        )

        parsed_url = parse_url(
            "https://gitlab.com/gitlab-org/gl-openshift/openshift-demos/openshift-custom-pipeline/-/commit/2b6494bdf8ad35073aafe36ca8a1bdfaf3dc72d1?private_token=PRIVATE"
        )
        self.assertEqual(
            parsed_url["project"],
            "gitlab-org/gl-openshift/openshift-demos/openshift-custom-pipeline",
        )
        self.assertEqual(parsed_url["tag"], "2b6494bdf8ad35073aafe36ca8a1bdfaf3dc72d1")
        self.assertEqual(parsed_url["private_token"], "PRIVATE")
        self.assertEqual(mock_get.call_count, 2)

        # default global token
        with self.settings(GITLAB_TOKEN="MY_GITLAB_TOKEN"):
            parsed_url = parse_url(
                "https://gitlab.com/mariusandra/helloworldplugin?private_token=PRIVATE",
                get_latest_if_none=True,
            )
            self.assertEqual(parsed_url["type"], "gitlab")
            self.assertEqual(parsed_url["project"], "mariusandra/helloworldplugin")
            self.assertEqual(parsed_url["tag"], "ff78cbe1d70316055c610a962a8355a4616d874b")
            self.assertEqual(parsed_url["private_token"], "PRIVATE")
            self.assertEqual(mock_get.call_count, 3)
            mock_get.assert_called_with(
                "https://gitlab.com/api/v4/projects/mariusandra%2Fhelloworldplugin/repository/commits",
                headers={"Authorization": "Bearer PRIVATE"},
            )

            parsed_url = parse_url(
                "https://gitlab.com/mariusandra/helloworldplugin",
                get_latest_if_none=True,
            )
            self.assertEqual(parsed_url["type"], "gitlab")
            self.assertEqual(parsed_url["project"], "mariusandra/helloworldplugin")
            self.assertEqual(parsed_url["tag"], "ff78cbe1d70316055c610a962a8355a4616d874b")
            self.assertEqual(parsed_url.get("private_token", None), None)
            self.assertEqual(mock_get.call_count, 4)
            mock_get.assert_called_with(
                "https://gitlab.com/api/v4/projects/mariusandra%2Fhelloworldplugin/repository/commits",
                headers={"Authorization": "Bearer MY_GITLAB_TOKEN"},
            )

    def test_parse_npm_urls(self, mock_get):
        parsed_url = parse_url("https://www.npmjs.com/package/posthog-helloworld-plugin")
        self.assertEqual(parsed_url["type"], "npm")
        self.assertEqual(parsed_url["pkg"], "posthog-helloworld-plugin")
        self.assertEqual(parsed_url.get("tag", None), None)
        self.assertEqual(mock_get.call_count, 0)

        parsed_url = parse_url("https://www.npmjs.com/package/@posthog/helloworldplugin")
        self.assertEqual(parsed_url["type"], "npm")
        self.assertEqual(parsed_url["pkg"], "@posthog/helloworldplugin")
        self.assertEqual(parsed_url.get("tag", None), None)
        self.assertEqual(mock_get.call_count, 0)

        parsed_url = parse_url(
            "https://www.npmjs.com/package/posthog-helloworld-plugin",
            get_latest_if_none=True,
        )
        self.assertEqual(parsed_url["type"], "npm")
        self.assertEqual(parsed_url["pkg"], "posthog-helloworld-plugin")
        self.assertEqual(parsed_url["tag"], "MOCK")
        self.assertEqual(mock_get.call_count, 1)
        mock_get.assert_called_with("https://registry.npmjs.org/posthog-helloworld-plugin/latest", headers={})

        parsed_url = parse_url(
            "https://www.npmjs.com/package/@posthog/helloworldplugin",
            get_latest_if_none=True,
        )
        self.assertEqual(parsed_url["type"], "npm")
        self.assertEqual(parsed_url["pkg"], "@posthog/helloworldplugin")
        self.assertEqual(parsed_url["tag"], "MOCK")
        self.assertEqual(mock_get.call_count, 2)
        mock_get.assert_called_with("https://registry.npmjs.org/@posthog/helloworldplugin/latest", headers={})

        parsed_url = parse_url("https://www.npmjs.com/package/posthog-helloworld-plugin/v/0.0.0")
        self.assertEqual(parsed_url["type"], "npm")
        self.assertEqual(parsed_url["pkg"], "posthog-helloworld-plugin")
        self.assertEqual(parsed_url["tag"], "0.0.0")
        self.assertEqual(mock_get.call_count, 2)

        parsed_url = parse_url("https://www.npmjs.com/package/@posthog/helloworldplugin/v/0.0.0")
        self.assertEqual(parsed_url["type"], "npm")
        self.assertEqual(parsed_url["pkg"], "@posthog/helloworldplugin")
        self.assertEqual(parsed_url["tag"], "0.0.0")
        self.assertEqual(mock_get.call_count, 2)

        parsed_url = parse_url(
            "https://www.npmjs.com/package/posthog-helloworld-plugin/v/0.0.0",
            get_latest_if_none=True,
        )
        self.assertEqual(parsed_url["type"], "npm")
        self.assertEqual(parsed_url["pkg"], "posthog-helloworld-plugin")
        self.assertEqual(parsed_url["tag"], "0.0.0")
        self.assertEqual(mock_get.call_count, 2)

        # private tokens
        parsed_url = parse_url(
            "https://www.npmjs.com/package/posthog-helloworld-plugin?private_token=TOKEN",
            get_latest_if_none=True,
        )
        self.assertEqual(parsed_url["type"], "npm")
        self.assertEqual(parsed_url["pkg"], "posthog-helloworld-plugin")
        self.assertEqual(parsed_url["tag"], "MOCK")
        self.assertEqual(parsed_url["private_token"], "TOKEN")
        self.assertEqual(mock_get.call_count, 3)
        mock_get.assert_called_with(
            "https://registry.npmjs.org/posthog-helloworld-plugin/latest",
            headers={"Authorization": "Bearer TOKEN"},
        )

        parsed_url = parse_url("https://www.npmjs.com/package/posthog-helloworld-plugin/v/0.0.0?private_token=TOKEN")
        self.assertEqual(parsed_url["type"], "npm")
        self.assertEqual(parsed_url["pkg"], "posthog-helloworld-plugin")
        self.assertEqual(parsed_url["tag"], "0.0.0")
        self.assertEqual(parsed_url["private_token"], "TOKEN")
        self.assertEqual(mock_get.call_count, 3)

        parsed_url = parse_url("https://www.npmjs.com/package/@posthog/helloworldplugin/v/0.0.0?private_token=TOKEN")
        self.assertEqual(parsed_url["type"], "npm")
        self.assertEqual(parsed_url["pkg"], "@posthog/helloworldplugin")
        self.assertEqual(parsed_url["tag"], "0.0.0")
        self.assertEqual(parsed_url["private_token"], "TOKEN")
        self.assertEqual(mock_get.call_count, 3)

        # default global token
        with self.settings(NPM_TOKEN="MY_NPM_TOKEN"):
            parsed_url = parse_url(
                "https://www.npmjs.com/package/posthog-helloworld-plugin?private_token=TOKEN",
                get_latest_if_none=True,
            )
            self.assertEqual(parsed_url["type"], "npm")
            self.assertEqual(parsed_url["pkg"], "posthog-helloworld-plugin")
            self.assertEqual(parsed_url["tag"], "MOCK")
            self.assertEqual(parsed_url["private_token"], "TOKEN")
            self.assertEqual(mock_get.call_count, 4)
            mock_get.assert_called_with(
                "https://registry.npmjs.org/posthog-helloworld-plugin/latest",
                headers={"Authorization": "Bearer TOKEN"},
            )

            parsed_url = parse_url(
                "https://www.npmjs.com/package/posthog-helloworld-plugin",
                get_latest_if_none=True,
            )
            self.assertEqual(parsed_url["type"], "npm")
            self.assertEqual(parsed_url["pkg"], "posthog-helloworld-plugin")
            self.assertEqual(parsed_url["tag"], "MOCK")
            self.assertEqual(parsed_url.get("private_token", None), None)
            self.assertEqual(mock_get.call_count, 5)
            mock_get.assert_called_with(
                "https://registry.npmjs.org/posthog-helloworld-plugin/latest",
                headers={"Authorization": "Bearer MY_NPM_TOKEN"},
            )

    def test_download_plugin_archive_github(self, mock_get):
        plugin_github_zip_1 = download_plugin_archive(
            "https://www.github.com/PostHog/helloworldplugin/commit/82c9218ee40f561b7f37a22d6b6a0ca82887ee3e",
            HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
        )
        self.assertEqual(plugin_github_zip_1, base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]))
        self.assertEqual(mock_get.call_count, 1)
        mock_get.assert_called_with(
            "https://github.com/PostHog/helloworldplugin/archive/d5aa1d2b8a534f37cd93be48b214f490ef9ee904.zip",
            headers={},
        )

        plugin_github_zip_2 = download_plugin_archive(
            "https://www.github.com/PostHog/helloworldplugin/commit/{}".format(HELLO_WORLD_PLUGIN_GITHUB_ZIP[0])
        )
        self.assertEqual(plugin_github_zip_2, base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]))
        self.assertEqual(mock_get.call_count, 2)
        mock_get.assert_called_with(
            "https://github.com/PostHog/helloworldplugin/archive/d5aa1d2b8a534f37cd93be48b214f490ef9ee904.zip",
            headers={},
        )

        plugin_github_zip_3 = download_plugin_archive(
            "https://www.github.com/PostHog/helloworldplugin/commit/{}?private_token=TOKEN".format(
                HELLO_WORLD_PLUGIN_GITHUB_ZIP[0]
            )
        )
        self.assertEqual(plugin_github_zip_3, base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]))
        self.assertEqual(mock_get.call_count, 3)
        mock_get.assert_called_with(
            "https://github.com/PostHog/helloworldplugin/archive/d5aa1d2b8a534f37cd93be48b214f490ef9ee904.zip",
            headers={"Authorization": "token TOKEN"},
        )

        with self.settings(GITHUB_TOKEN="MY_GITHUB_TOKEN"):
            plugin_github_zip_4 = download_plugin_archive(
                "https://www.github.com/PostHog/helloworldplugin/commit/{}?private_token=TOKEN".format(
                    HELLO_WORLD_PLUGIN_GITHUB_ZIP[0]
                )
            )
            self.assertEqual(plugin_github_zip_4, base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]))
            self.assertEqual(mock_get.call_count, 4)
            mock_get.assert_called_with(
                "https://github.com/PostHog/helloworldplugin/archive/d5aa1d2b8a534f37cd93be48b214f490ef9ee904.zip",
                headers={"Authorization": "token TOKEN"},
            )

            plugin_github_zip_5 = download_plugin_archive(
                "https://www.github.com/PostHog/helloworldplugin/commit/{}".format(HELLO_WORLD_PLUGIN_GITHUB_ZIP[0])
            )
            self.assertEqual(plugin_github_zip_5, base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]))
            self.assertEqual(mock_get.call_count, 5)
            mock_get.assert_called_with(
                "https://github.com/PostHog/helloworldplugin/archive/d5aa1d2b8a534f37cd93be48b214f490ef9ee904.zip",
                headers={"Authorization": "token MY_GITHUB_TOKEN"},
            )

        # test that subdirectory is properly extracted into its own archive
        plugin_github_zip_6 = download_plugin_archive(
            "https://www.github.com/PostHog/helloworldplugin/tree/main/app",
            HELLO_WORLD_PLUGIN_GITHUB_SUBDIR_ZIP[0],
        )

        zip_file = ZipFile(io.BytesIO(plugin_github_zip_6), "r")

        self.assertEqual(mock_get.call_count, 6)
        mock_get.assert_called_with(
            "https://github.com/PostHog/helloworldplugin/archive/f5a9ea85adaafe7c99014b7e8e0982c447631d54.zip",
            headers={},
        )
        self.assertEqual(
            zip_file.getinfo("helloworldplugin-imageless-version/index.js").CRC,
            1913611967,
        )
        self.assertEqual(
            zip_file.getinfo("helloworldplugin-imageless-version/plugin.json").CRC,
            2713501883,
        )

    def test_download_plugin_archive_gitlab(self, mock_get):
        plugin_gitlab = download_plugin_archive(
            "https://www.gitlab.com/mariusandra/helloworldplugin/-/commit/ff78cbe1d70316055c610a962a8355a4616d874b",
            HELLO_WORLD_PLUGIN_GITLAB_ZIP[0],
        )
        self.assertEqual(plugin_gitlab, base64.b64decode(HELLO_WORLD_PLUGIN_GITLAB_ZIP[1]))
        self.assertEqual(mock_get.call_count, 1)
        mock_get.assert_called_with(
            "https://gitlab.com/api/v4/projects/mariusandra%2Fhelloworldplugin/repository/archive.zip?sha=ff78cbe1d70316055c610a962a8355a4616d874b",
            headers={},
        )

        plugin_gitlab = download_plugin_archive(
            "https://www.gitlab.com/mariusandra/helloworldplugin/-/commit/ff78cbe1d70316055c610a962a8355a4616d874b?private_token=PRIVATE_TOKEN",
            HELLO_WORLD_PLUGIN_GITLAB_ZIP[0],
        )
        self.assertEqual(plugin_gitlab, base64.b64decode(HELLO_WORLD_PLUGIN_GITLAB_ZIP[1]))
        self.assertEqual(mock_get.call_count, 2)
        mock_get.assert_called_with(
            "https://gitlab.com/api/v4/projects/mariusandra%2Fhelloworldplugin/repository/archive.zip?sha=ff78cbe1d70316055c610a962a8355a4616d874b",
            headers={"Authorization": "Bearer PRIVATE_TOKEN"},
        )

        with self.settings(GITLAB_TOKEN="MY_GITLAB_TOKEN"):
            plugin_gitlab = download_plugin_archive(
                "https://www.gitlab.com/mariusandra/helloworldplugin/-/commit/ff78cbe1d70316055c610a962a8355a4616d874b?private_token=PRIVATE_TOKEN",
                HELLO_WORLD_PLUGIN_GITLAB_ZIP[0],
            )
            self.assertEqual(plugin_gitlab, base64.b64decode(HELLO_WORLD_PLUGIN_GITLAB_ZIP[1]))
            self.assertEqual(mock_get.call_count, 3)
            mock_get.assert_called_with(
                "https://gitlab.com/api/v4/projects/mariusandra%2Fhelloworldplugin/repository/archive.zip?sha=ff78cbe1d70316055c610a962a8355a4616d874b",
                headers={"Authorization": "Bearer PRIVATE_TOKEN"},
            )

            plugin_gitlab = download_plugin_archive(
                "https://www.gitlab.com/mariusandra/helloworldplugin/-/commit/ff78cbe1d70316055c610a962a8355a4616d874b",
                HELLO_WORLD_PLUGIN_GITLAB_ZIP[0],
            )
            self.assertEqual(plugin_gitlab, base64.b64decode(HELLO_WORLD_PLUGIN_GITLAB_ZIP[1]))
            self.assertEqual(mock_get.call_count, 4)
            mock_get.assert_called_with(
                "https://gitlab.com/api/v4/projects/mariusandra%2Fhelloworldplugin/repository/archive.zip?sha=ff78cbe1d70316055c610a962a8355a4616d874b",
                headers={"Authorization": "Bearer MY_GITLAB_TOKEN"},
            )

    def test_download_plugin_archive_npm(self, mock_get):
        plugin_npm_tgz = download_plugin_archive("https://www.npmjs.com/package/posthog-helloworld-plugin/v/0.0.0")
        self.assertEqual(plugin_npm_tgz, base64.b64decode(HELLO_WORLD_PLUGIN_NPM_TGZ[1]))
        self.assertEqual(mock_get.call_count, 1)
        mock_get.assert_called_with(
            "https://registry.npmjs.org/posthog-helloworld-plugin/-/posthog-helloworld-plugin-0.0.0.tgz",
            headers={},
        )

        plugin_npm_tgz = download_plugin_archive(
            "https://www.npmjs.com/package/@posthog/helloworldplugin/v/0.0.0?private_token=TOKEN"
        )
        self.assertEqual(plugin_npm_tgz, base64.b64decode(HELLO_WORLD_PLUGIN_NPM_TGZ[1]))
        self.assertEqual(mock_get.call_count, 2)
        mock_get.assert_called_with(
            "https://registry.npmjs.org/@posthog/helloworldplugin/-/helloworldplugin-0.0.0.tgz",
            headers={"Authorization": "Bearer TOKEN"},
        )

        with self.settings(NPM_TOKEN="MY_NPM_TOKEN"):
            plugin_npm_tgz = download_plugin_archive(
                "https://www.npmjs.com/package/@posthog/helloworldplugin/v/0.0.0?private_token=TOKEN"
            )
            self.assertEqual(plugin_npm_tgz, base64.b64decode(HELLO_WORLD_PLUGIN_NPM_TGZ[1]))
            self.assertEqual(mock_get.call_count, 3)
            mock_get.assert_called_with(
                "https://registry.npmjs.org/@posthog/helloworldplugin/-/helloworldplugin-0.0.0.tgz",
                headers={"Authorization": "Bearer TOKEN"},
            )

            plugin_npm_tgz = download_plugin_archive("https://www.npmjs.com/package/@posthog/helloworldplugin/v/0.0.0")
            self.assertEqual(plugin_npm_tgz, base64.b64decode(HELLO_WORLD_PLUGIN_NPM_TGZ[1]))
            self.assertEqual(mock_get.call_count, 4)
            mock_get.assert_called_with(
                "https://registry.npmjs.org/@posthog/helloworldplugin/-/helloworldplugin-0.0.0.tgz",
                headers={"Authorization": "Bearer MY_NPM_TOKEN"},
            )

    def test_get_file_from_archive(self, mock_get):
        plugin_json_zip = cast(
            dict,
            get_file_from_archive(base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]), "plugin.json"),
        )
        self.assertEqual(plugin_json_zip["name"], "helloworldplugin")
        self.assertEqual(plugin_json_zip["url"], "https://github.com/PostHog/helloworldplugin")
        self.assertEqual(plugin_json_zip["description"], "Greet the World and Foo a Bar, JS edition!")

        plugin_json_zip = cast(
            dict,
            get_file_from_archive(base64.b64decode(HELLO_WORLD_PLUGIN_GITLAB_ZIP[1]), "plugin.json"),
        )
        self.assertEqual(plugin_json_zip["name"], "hellojsplugin")
        self.assertEqual(plugin_json_zip["url"], "https://github.com/PosthHog/helloworldplugin")
        self.assertEqual(plugin_json_zip["description"], "Greet the World and Foo a Bar, JS edition!")

        plugin_json_tgz = cast(
            dict,
            get_file_from_archive(base64.b64decode(HELLO_WORLD_PLUGIN_NPM_TGZ[1]), "plugin.json"),
        )
        self.assertEqual(plugin_json_tgz["name"], "helloworldplugin")
        self.assertEqual(plugin_json_tgz["url"], "https://github.com/PostHog/helloworldplugin")
        self.assertEqual(plugin_json_tgz["description"], "Greet the World and Foo a Bar, JS edition!")

    def test_put_json_into_zip_archive(self, mock_get):
        archive = base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1])
        plugin_json = cast(dict, get_file_from_archive(archive, "plugin.json"))
        plugin_json["posthogVersion"] = "0.0.0"

        # check that we can override files
        new_archive = put_json_into_zip_archive(archive, plugin_json, "plugin.json")
        new_plugin_json = cast(dict, get_file_from_zip_archive(new_archive, "plugin.json", json_parse=True))
        self.assertEqual(new_plugin_json["posthogVersion"], "0.0.0")

        # check that new the file is there
        new_archive_2 = put_json_into_zip_archive(archive, plugin_json, "plugin2.json")
        new_plugin_json_2 = cast(dict, get_file_from_archive(new_archive_2, "plugin2.json"))
        self.assertEqual(new_plugin_json_2["posthogVersion"], "0.0.0")

        # check that old files are intact
        old_plugin_json_2 = cast(dict, get_file_from_archive(new_archive_2, "plugin.json"))
        self.assertEqual(old_plugin_json_2["name"], "helloworldplugin")
