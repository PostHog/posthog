import json
from pathlib import Path

from unittest.mock import MagicMock, patch

from dags.sdk_doctor.github_sdk_versions import (
    fetch_android_sdk_data,
    fetch_dotnet_sdk_data,
    fetch_elixir_sdk_data,
    fetch_flutter_sdk_data,
    fetch_go_sdk_data,
    fetch_ios_sdk_data,
    fetch_node_sdk_data,
    fetch_php_sdk_data,
    fetch_python_sdk_data,
    fetch_react_native_sdk_data,
    fetch_ruby_sdk_data,
    fetch_web_sdk_data,
)

# NOTE: Fixtures are defined as they were in October 10, 2025
# They can be updated by running the following Python Script:
#
# ```python
# import requests
# from pathlib import Path
#
# FIXTURES = Path(__file__).parent / "fixtures"
# CHANGELOGS = FIXTURES / "changelogs"
# RELEASES = FIXTURES / "releases"
#
# changelogs = {
#     "php_changelog.md": "https://raw.githubusercontent.com/PostHog/posthog-php/master/History.md",
#     "ruby_changelog.md": "https://raw.githubusercontent.com/PostHog/posthog-ruby/main/CHANGELOG.md",
#     "elixir_changelog.md": "https://raw.githubusercontent.com/PostHog/posthog-elixir/master/CHANGELOG.md",
# }
#
# releases = {
#     "posthog_js_releases.json": "https://api.github.com/repos/PostHog/posthog-js/releases?per_page=25",
#     "posthog_python_releases.json": "https://api.github.com/repos/PostHog/posthog-python/releases?per_page=10",
#     "posthog_flutter_releases.json": "https://api.github.com/repos/PostHog/posthog-flutter/releases?per_page=10",
#     "posthog_ios_releases.json": "https://api.github.com/repos/PostHog/posthog-ios/releases?per_page=10",
#     "posthog_android_releases.json": "https://api.github.com/repos/PostHog/posthog-android/releases?per_page=10",
#     "posthog_go_releases.json": "https://api.github.com/repos/PostHog/posthog-go/releases?per_page=10",
#     "dotnet_releases.json": "https://api.github.com/repos/PostHog/posthog-dotnet/releases?per_page=10",
# }
#
# for filename, url in changelogs.items():
#     print(f"Downloading {filename}...")
#     r = requests.get(url)
#     (CHANGELOGS / filename).write_text(r.text)
#
# for filename, url in releases.items():
#     print(f"Downloading {filename}...")
#     r = requests.get(url)
#     (RELEASES / filename).write_text(r.text)
# ```

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CHANGELOGS_DIR = FIXTURES_DIR / "changelogs"
RELEASES_DIR = FIXTURES_DIR / "releases"


def load_changelog(filename: str) -> str:
    """Load a changelog file from the changelogs directory."""
    with open(CHANGELOGS_DIR / filename) as f:
        return f.read()


def load_releases(filename: str) -> dict:
    """Load a releases JSON file from the releases directory."""
    with open(RELEASES_DIR / filename) as f:
        return json.load(f)


class TestFetchSdkDataBase:
    def setup_ok_json_mock(self, mock_get, data):
        response = MagicMock()
        response.ok = True
        response.status_code = 200
        response.json.return_value = data
        mock_get.side_effect = [response]

    def setup_ok_text_mock(self, mock_get, data):
        response = MagicMock()
        response.ok = True
        response.status_code = 200
        response.text = data
        mock_get.side_effect = [response]


class TestFetchWebSdkData(TestFetchSdkDataBase):
    @patch("dags.sdk_doctor.github_sdk_versions.requests.get")
    def test_fetch_web_sdk_data_success(self, mock_get):
        releases_data = load_releases("posthog_js_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_web_sdk_data()

        assert result is not None
        assert result["latestVersion"] == "1.275.0"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "1.275.0" in result["releaseDates"]
        assert result["releaseDates"]["1.275.0"] == "2025-10-10T14:06:17Z"
        assert mock_get.call_count == 1

    @patch("dags.sdk_doctor.github_sdk_versions.requests.get")
    def test_fetch_web_sdk_data_request_failure(self, mock_get):
        response = MagicMock()
        response.ok = False
        response.status_code = 404
        mock_get.side_effect = [response]

        result = fetch_web_sdk_data()

        assert result is None


class TestFetchPythonSdkData(TestFetchSdkDataBase):
    @patch("dags.sdk_doctor.github_sdk_versions.requests.get")
    def test_fetch_python_sdk_data_success(self, mock_get):
        releases_data = load_releases("posthog_python_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_python_sdk_data()

        assert result is not None
        assert result["latestVersion"] == "6.7.6"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "6.7.6" in result["releaseDates"]
        assert result["releaseDates"]["6.7.6"] == "2025-09-22T18:11:17Z"
        assert mock_get.call_count == 1


class TestFetchNodeSdkData(TestFetchSdkDataBase):
    @patch("dags.sdk_doctor.github_sdk_versions.requests.get")
    def test_fetch_node_sdk_data_success(self, mock_get):
        releases_data = load_releases("posthog_js_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_node_sdk_data()

        assert result is not None
        assert result["latestVersion"] == "5.9.5"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert mock_get.call_count == 1


class TestFetchReactNativeSdkData(TestFetchSdkDataBase):
    @patch("dags.sdk_doctor.github_sdk_versions.requests.get")
    def test_fetch_react_native_sdk_data_success(self, mock_get):
        releases_data = load_releases("posthog_js_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_react_native_sdk_data()

        assert result is not None
        assert result["latestVersion"] == "4.9.1"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert mock_get.call_count == 1


class TestFetchFlutterSdkData(TestFetchSdkDataBase):
    @patch("dags.sdk_doctor.github_sdk_versions.requests.get")
    def test_fetch_flutter_sdk_data_success(self, mock_get):
        releases_data = load_releases("posthog_flutter_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_flutter_sdk_data()

        assert result is not None
        assert result["latestVersion"] == "5.6.0"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "5.6.0" in result["releaseDates"]
        assert result["releaseDates"]["5.6.0"] == "2025-10-06T11:14:06Z"
        assert mock_get.call_count == 1


class TestFetchIosSdkData(TestFetchSdkDataBase):
    @patch("dags.sdk_doctor.github_sdk_versions.requests.get")
    def test_fetch_ios_sdk_data_success(self, mock_get):
        releases_data = load_releases("posthog_ios_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_ios_sdk_data()

        assert result is not None
        assert result["latestVersion"] == "3.32.0"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "3.32.0" in result["releaseDates"]
        assert result["releaseDates"]["3.32.0"] == "2025-10-03T14:21:35Z"
        assert mock_get.call_count == 1


class TestFetchAndroidSdkData(TestFetchSdkDataBase):
    @patch("dags.sdk_doctor.github_sdk_versions.requests.get")
    def test_fetch_android_sdk_data_success(self, mock_get):
        releases_data = load_releases("posthog_android_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_android_sdk_data()

        assert result is not None
        assert result["latestVersion"] == "3.23.0"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "3.23.0" in result["releaseDates"]
        assert result["releaseDates"]["3.23.0"] == "2025-10-06T09:13:27Z"
        assert mock_get.call_count == 1


class TestFetchGoSdkData(TestFetchSdkDataBase):
    @patch("dags.sdk_doctor.github_sdk_versions.requests.get")
    def test_fetch_go_sdk_data_success(self, mock_get):
        releases_data = load_releases("posthog_go_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_go_sdk_data()

        assert result is not None
        assert result["latestVersion"] == "1.6.10"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "1.6.10" in result["releaseDates"]
        assert result["releaseDates"]["1.6.10"] == "2025-09-22T20:23:13Z"
        assert mock_get.call_count == 1


class TestFetchPhpSdkData(TestFetchSdkDataBase):
    @patch("dags.sdk_doctor.github_sdk_versions.requests.get")
    def test_fetch_php_sdk_data_success(self, mock_get):
        changelog_content = load_changelog("php_changelog.md")
        self.setup_ok_text_mock(mock_get, changelog_content)

        result = fetch_php_sdk_data()

        assert result is not None
        assert result["latestVersion"] == "3.7.1"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "3.7.1" in result["releaseDates"]
        assert result["releaseDates"]["3.7.1"] == "2025-09-26T00:00:00Z"
        assert mock_get.call_count == 1


class TestFetchRubySdkData(TestFetchSdkDataBase):
    @patch("dags.sdk_doctor.github_sdk_versions.requests.get")
    def test_fetch_ruby_sdk_data_success(self, mock_get):
        changelog_content = load_changelog("ruby_changelog.md")
        self.setup_ok_text_mock(mock_get, changelog_content)

        result = fetch_ruby_sdk_data()

        assert result is not None
        assert result["latestVersion"] == "3.3.2"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "3.3.2" in result["releaseDates"]
        assert result["releaseDates"]["3.3.2"] == "2025-09-26T00:00:00Z"
        assert mock_get.call_count == 1


class TestFetchElixirSdkData(TestFetchSdkDataBase):
    @patch("dags.sdk_doctor.github_sdk_versions.requests.get")
    def test_fetch_elixir_sdk_data_success(self, mock_get):
        changelog_content = load_changelog("elixir_changelog.md")
        self.setup_ok_text_mock(mock_get, changelog_content)

        result = fetch_elixir_sdk_data()

        assert result is not None
        assert result["latestVersion"] == "2.0.0"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "2.0.0" in result["releaseDates"]
        assert result["releaseDates"]["2.0.0"] == "2025-09-30T00:00:00Z"
        assert mock_get.call_count == 1


class TestFetchDotnetSdkData(TestFetchSdkDataBase):
    @patch("dags.sdk_doctor.github_sdk_versions.requests.get")
    def test_fetch_dotnet_sdk_data_success(self, mock_get):
        releases_data = load_releases("dotnet_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_dotnet_sdk_data()

        assert result is not None
        assert result["latestVersion"] == "2.0.1"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "2.0.1" in result["releaseDates"]
        assert result["releaseDates"]["2.0.1"] == "2025-09-28T19:40:53Z"
        assert mock_get.call_count == 1
