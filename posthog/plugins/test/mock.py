import json
import base64
from typing import Any, cast

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


class MockResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def ok(self) -> bool:
        return self.status_code < 300


class MockJSONResponse(MockResponse):
    def __init__(self, json_data: Any, status_code: int) -> None:
        super().__init__(status_code)
        self.json_data = json_data

    def json(self) -> Any:
        return self.json_data


class MockTextResponse(MockResponse):
    def __init__(self, text: str, status_code: int) -> None:
        super().__init__(status_code)
        self.text = text


class MockBase64Response(MockResponse):
    def __init__(self, base64_data: str | bytes, status_code: int) -> None:
        super().__init__(status_code)
        self.content = base64.b64decode(base64_data)


def _github_commits(repo: str, sha: str) -> list[dict[str, str]]:
    return [{"sha": sha, "html_url": f"https://www.github.com/{repo}/commit/{sha}"}]


def _gitlab_commits(project: str) -> list[dict[str, str]]:
    sha = "ff78cbe1d70316055c610a962a8355a4616d874b"
    return [{"id": sha, "web_url": f"https://gitlab.com/{project}/-/commit/{sha}"}]


POSTHOG_LATEST_COMMIT = _github_commits("PostHog/posthog", "MOCKLATESTCOMMIT")

GITHUB_COMMIT_FIXTURES: dict[str, Any] = {
    "https://api.github.com/repos/PostHog/posthog/commits?sha=&path=": POSTHOG_LATEST_COMMIT,
    "https://api.github.com/repos/PostHog/posthog/commits?sha=main&path=": POSTHOG_LATEST_COMMIT,
    "https://api.github.com/repos/PostHog/posthog/commits?sha=main&path=test/path/in/repo": POSTHOG_LATEST_COMMIT,
    "https://api.github.com/repos/PostHog/helloworldplugin/commits?sha=&path=": _github_commits(
        "PostHog/helloworldplugin", HELLO_WORLD_PLUGIN_GITHUB_ZIP[0]
    ),
    # This one answers with a single commit rather than a list, so the parser sees both shapes
    "https://api.github.com/repos/PostHog/helloworldplugin/commits?sha=main&path=": {
        "commit": {"sha": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0]}
    },
}

GITHUB_ARCHIVE_FIXTURES: dict[str, str] = {
    f"https://github.com/PostHog/helloworldplugin/archive/{archive[0]}.zip": archive[1]
    for archive in (
        HELLO_WORLD_PLUGIN_GITHUB_ZIP,
        HELLO_WORLD_PLUGIN_GITHUB_ATTACHMENT_ZIP,
        HELLO_WORLD_PLUGIN_SECRET_GITHUB_ZIP,
        HELLO_WORLD_PLUGIN_GITHUB_SUBDIR_ZIP,
    )
}

# Installed from https://github.com/posthog-plugin/version-{equals,greater-than,less-than}/commit/{version}
VERSION_PLUGIN_URL_PREFIX = "https://github.com/posthog-plugin/version-"

INTEGRATIONS_REPOSITORY_URL = "https://raw.githubusercontent.com/PostHog/integrations-repository/main/plugins.json"

INTEGRATIONS_REPOSITORY_PLUGINS = [
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

GITLAB_COMMIT_PREFIXES: dict[str, Any] = {
    f"https://gitlab.com/api/v4/projects/mariusandra%2F{project}/repository/commits": _gitlab_commits(
        f"mariusandra/{project}"
    )
    for project in ("helloworldplugin", "helloworldplugin-other")
}

GITLAB_ARCHIVE_PREFIXES = [
    f"https://gitlab.com/api/v4/projects/mariusandra%2F{project}/repository/archive.zip"
    f"?sha={HELLO_WORLD_PLUGIN_GITLAB_ZIP[0]}"
    for project in ("helloworldplugin", "helloworldplugin-other")
]

NPM_PACKAGE_FIXTURES: dict[str, Any] = {
    "https://registry.npmjs.org/posthog-helloworld-plugin/latest": {
        "pkg": "posthog-helloworld-plugin",
        "version": "MOCK",
    },
    "https://registry.npmjs.org/@posthog/helloworldplugin/latest": {
        "pkg": "@posthog/helloworldplugin",
        "version": "MOCK",
    },
}

NPM_TARBALL_URLS = {
    "https://registry.npmjs.org/@posthog/helloworldplugin/-/helloworldplugin-0.0.0.tgz",
    "https://registry.npmjs.org/posthog-helloworld-plugin/-/posthog-helloworld-plugin-0.0.0.tgz",
}


def _version_plugin_archive(url: str) -> bytes:
    """Rewrite the hello world plugin.json so its posthogVersion comes from the URL."""
    url_repo = url.split("/")[4]
    url_version = url.split("/")[6].split(".zip")[0]

    archive = base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1])
    plugin_json = cast(dict, get_file_from_zip_archive(archive, "plugin.json", json_parse=True))
    plugin_json["posthogVersion"] = url_version

    if url_repo == "version-greater-than":
        plugin_json["posthogVersion"] = f">= {url_version}"

    if url_repo == "version-less-than":
        plugin_json["posthogVersion"] = f"< {url_version}"

    return base64.b64encode(put_json_into_zip_archive(archive, plugin_json, "plugin.json"))


def _github_fixture(url: str) -> MockResponse | None:
    if url in GITHUB_COMMIT_FIXTURES:
        return MockJSONResponse(GITHUB_COMMIT_FIXTURES[url], 200)

    if url in GITHUB_ARCHIVE_FIXTURES:
        return MockBase64Response(GITHUB_ARCHIVE_FIXTURES[url], 200)

    if url.startswith(VERSION_PLUGIN_URL_PREFIX):
        return MockBase64Response(_version_plugin_archive(url), 200)

    return None


def _gitlab_fixture(url: str) -> MockResponse | None:
    for prefix, commits in GITLAB_COMMIT_PREFIXES.items():
        if url.startswith(prefix):
            return MockJSONResponse(commits, 200)

    if any(url.startswith(prefix) for prefix in GITLAB_ARCHIVE_PREFIXES):
        return MockBase64Response(HELLO_WORLD_PLUGIN_GITLAB_ZIP[1], 200)

    return None


def _npm_fixture(url: str) -> MockResponse | None:
    if url in NPM_PACKAGE_FIXTURES:
        return MockJSONResponse(NPM_PACKAGE_FIXTURES[url], 200)

    if url in NPM_TARBALL_URLS:
        return MockBase64Response(HELLO_WORLD_PLUGIN_NPM_TGZ[1], 200)

    return None


def _plugin_repository_fixture(url: str) -> MockResponse | None:
    if url == INTEGRATIONS_REPOSITORY_URL:
        return MockTextResponse(json.dumps(INTEGRATIONS_REPOSITORY_PLUGINS), 200)

    return None


def mocked_plugin_requests_get(url: str, *args: Any, **kwargs: Any) -> MockResponse:
    for fixture in (_github_fixture, _gitlab_fixture, _npm_fixture, _plugin_repository_fixture):
        response = fixture(url)
        if response is not None:
            return response

    return MockJSONResponse(None, 404)
