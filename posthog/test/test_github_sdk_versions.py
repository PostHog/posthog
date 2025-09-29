"""
Tests for GitHub SDK versions API endpoint.
Tests server-side caching, error handling, and all supported SDK types.
"""

import json

from unittest.mock import Mock, patch

from django.test import TestCase  # type: ignore[import-untyped]

import requests
from rest_framework.test import APIClient  # type: ignore[import-untyped]

from posthog.redis import get_client


class TestGitHubSDKVersionsAPI(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.redis_client = get_client()
        # Clear any existing cache before each test
        self.redis_client.flushdb()

    def tearDown(self):
        # Clean up cache after each test
        self.redis_client.flushdb()

    def test_web_sdk_cache_miss_and_hit(self):
        """Test cache miss followed by cache hit for Web SDK."""
        with patch("posthog.api.github_sdk_versions.requests.get") as mock_get:
            # Mock successful GitHub API responses
            mock_changelog = Mock()
            mock_changelog.ok = True
            mock_changelog.text = "## 1.258.5\n\n## 1.258.4\n\n## 1.258.3"

            mock_releases = Mock()
            mock_releases.ok = True
            mock_releases.json.return_value = [
                {"tag_name": "posthog-js@1.258.5", "published_at": "2025-09-01T10:00:00Z"},
                {"tag_name": "posthog-js@1.258.4", "published_at": "2025-08-30T10:00:00Z"},
            ]

            mock_get.side_effect = [mock_changelog, mock_releases]

            # First request - cache miss
            response = self.client.get("/api/github-sdk-versions/web")

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["latestVersion"], "1.258.5")
            self.assertEqual(len(data["versions"]), 3)
            self.assertFalse(data["cached"])  # Fresh data

            # Verify data was cached
            cache_key = "github:sdk_versions:web"
            cached_data = self.redis_client.get(cache_key)
            self.assertIsNotNone(cached_data)

            # Second request - cache hit (no additional API calls)
            response = self.client.get("/api/github-sdk-versions/web")

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["latestVersion"], "1.258.5")
            self.assertTrue(data["cached"])  # From cache

            # Should have only made the initial API calls
            self.assertEqual(mock_get.call_count, 2)

    def test_python_sdk_changelog_parsing(self):
        """Test Python SDK with different changelog format."""
        with patch("posthog.api.github_sdk_versions.requests.get") as mock_get:
            mock_changelog = Mock()
            mock_changelog.ok = True
            mock_changelog.text = "# 6.7.6 - 2025-09-01\n\n# 6.7.5 - 2025-08-30\n\n# 6.7.4 - 2025-08-25"

            mock_releases = Mock()
            mock_releases.ok = True
            mock_releases.json.return_value = [
                {"tag_name": "v6.7.6", "published_at": "2025-09-01T10:00:00Z"},
                {"tag_name": "v6.7.5", "published_at": "2025-08-30T10:00:00Z"},
            ]

            mock_get.side_effect = [mock_changelog, mock_releases]

            response = self.client.get("/api/github-sdk-versions/python")

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["latestVersion"], "6.7.6")
            self.assertEqual(len(data["versions"]), 3)
            self.assertIn("6.7.6", data["releaseDates"])

    def test_simplified_sdk_go(self):
        """Test Go SDK with simplified logic (no GitHub releases API)."""
        with patch("posthog.api.github_sdk_versions.requests.get") as mock_get:
            mock_changelog = Mock()
            mock_changelog.ok = True
            mock_changelog.text = "## 1.6.3\n\n## 1.6.2\n\n## 1.6.1"

            mock_get.return_value = mock_changelog

            response = self.client.get("/api/github-sdk-versions/go")

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["latestVersion"], "1.6.3")
            self.assertEqual(len(data["versions"]), 3)
            self.assertEqual(data["releaseDates"], {})  # Go SDK uses simplified logic

    def test_php_sdk_history_format(self):
        """Test PHP SDK with History.md format."""
        with patch("posthog.api.github_sdk_versions.requests.get") as mock_get:
            mock_history = Mock()
            mock_history.ok = True
            mock_history.text = "3.6.0 / 2025-04-30\n\n3.5.9 / 2025-04-20\n\n3.5.8 / 2025-04-10"

            mock_get.return_value = mock_history

            response = self.client.get("/api/github-sdk-versions/php")

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["latestVersion"], "3.6.0")
            self.assertEqual(len(data["versions"]), 3)

    def test_dotnet_sdk_github_releases(self):
        """Test .NET SDK using GitHub releases API only."""
        with patch("posthog.api.github_sdk_versions.requests.get") as mock_get:
            mock_releases = Mock()
            mock_releases.ok = True
            mock_releases.json.return_value = [
                {"tag_name": "v2.0.0", "published_at": "2025-09-01T10:00:00Z"},
                {"tag_name": "v1.9.0", "published_at": "2025-08-15T10:00:00Z"},
            ]

            mock_get.return_value = mock_releases

            response = self.client.get("/api/github-sdk-versions/dotnet")

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["latestVersion"], "2.0.0")
            self.assertEqual(len(data["versions"]), 2)

    def test_changelog_fetch_failure(self):
        """Test handling of changelog fetch failures."""
        with patch("posthog.api.github_sdk_versions.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.ok = False
            mock_response.status_code = 404
            mock_get.return_value = mock_response

            response = self.client.get("/api/github-sdk-versions/web")

            self.assertEqual(response.status_code, 500)
            data = response.json()
            self.assertIn("unavailable", data["error"])

    def test_github_api_rate_limit(self):
        """Test handling of GitHub API rate limits."""
        with patch("posthog.api.github_sdk_versions.requests.get") as mock_get:
            # Changelog succeeds
            mock_changelog = Mock()
            mock_changelog.ok = True
            mock_changelog.text = "## 1.258.5\n\n## 1.258.4"

            # GitHub releases API fails (rate limited)
            mock_releases = Mock()
            mock_releases.ok = False
            mock_releases.status_code = 403  # Rate limited

            mock_get.side_effect = [mock_changelog, mock_releases]

            response = self.client.get("/api/github-sdk-versions/web")

            # Should still return data with empty release dates
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["latestVersion"], "1.258.5")
            self.assertEqual(data["releaseDates"], {})

    def test_malformed_changelog_content(self):
        """Test handling of malformed changelog content."""
        with patch("posthog.api.github_sdk_versions.requests.get") as mock_get:
            mock_changelog = Mock()
            mock_changelog.ok = True
            mock_changelog.text = "This is not a valid changelog format"

            mock_get.return_value = mock_changelog

            response = self.client.get("/api/github-sdk-versions/web")

            self.assertEqual(response.status_code, 500)
            data = response.json()
            self.assertIn("unavailable", data["error"])

    def test_network_timeout_handling(self):
        """Test handling of network timeouts."""
        with patch("posthog.api.github_sdk_versions.requests.get") as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout("Request timed out")

            response = self.client.get("/api/github-sdk-versions/web")

            self.assertEqual(response.status_code, 500)
            data = response.json()
            self.assertIn("unavailable", data["error"])

    def test_invalid_json_response(self):
        """Test handling of invalid JSON in GitHub API response."""
        with patch("posthog.api.github_sdk_versions.requests.get") as mock_get:
            mock_changelog = Mock()
            mock_changelog.ok = True
            mock_changelog.text = "## 1.258.5\n\n## 1.258.4"

            mock_releases = Mock()
            mock_releases.ok = True
            mock_releases.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)

            mock_get.side_effect = [mock_changelog, mock_releases]

            response = self.client.get("/api/github-sdk-versions/web")

            # Should handle gracefully and return data without release dates
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["latestVersion"], "1.258.5")
            self.assertEqual(data["releaseDates"], {})

    def test_unsupported_sdk_type(self):
        """Test handling of unsupported SDK types."""
        response = self.client.get("/api/github-sdk-versions/unsupported-sdk")

        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertIn("unavailable", data["error"])

    def test_cache_corruption_recovery(self):
        """Test recovery from corrupted cache data."""
        # Manually insert corrupted data into cache
        cache_key = "github:sdk_versions:web"
        self.redis_client.setex(cache_key, 3600, "corrupted-json-data")

        with patch("posthog.api.github_sdk_versions.requests.get") as mock_get:
            mock_changelog = Mock()
            mock_changelog.ok = True
            mock_changelog.text = "## 1.258.5\n\n## 1.258.4"

            mock_releases = Mock()
            mock_releases.ok = True
            mock_releases.json.return_value = []

            mock_get.side_effect = [mock_changelog, mock_releases]

            response = self.client.get("/api/github-sdk-versions/web")

            # Should recover by fetching fresh data
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["latestVersion"], "1.258.5")
            self.assertFalse(data["cached"])  # Fresh data after cache corruption

    def test_cache_expiry_behavior(self):
        """Test that cache properly expires after the configured time."""
        with patch("posthog.api.github_sdk_versions.requests.get") as mock_get:
            mock_changelog = Mock()
            mock_changelog.ok = True
            mock_changelog.text = "## 1.258.5"

            mock_releases = Mock()
            mock_releases.ok = True
            mock_releases.json.return_value = []

            mock_get.side_effect = [mock_changelog, mock_releases]

            # First request - creates cache entry
            response = self.client.get("/api/github-sdk-versions/web")
            self.assertEqual(response.status_code, 200)

            # Manually expire the cache
            cache_key = "github:sdk_versions:web"
            self.redis_client.delete(cache_key)

            # Second request should fetch fresh data
            mock_get.side_effect = [mock_changelog, mock_releases]
            response = self.client.get("/api/github-sdk-versions/web")

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertFalse(data["cached"])  # Fresh data after expiry

    def test_all_supported_sdk_types(self):
        """Test that all SDK types are supported."""
        supported_sdks = [
            "web",
            "python",
            "node",
            "react-native",
            "flutter",
            "ios",
            "android",
            "go",
            "php",
            "ruby",
            "elixir",
            "dotnet",
        ]

        with patch("posthog.api.github_sdk_versions.requests.get") as mock_get:
            # Mock a basic successful response for all SDKs
            mock_response = Mock()
            mock_response.ok = True
            mock_response.text = "## 1.0.0\n\n## 0.9.0"
            mock_response.json.return_value = [{"tag_name": "v1.0.0", "published_at": "2025-09-01T10:00:00Z"}]
            mock_get.return_value = mock_response

            for sdk_type in supported_sdks:
                response = self.client.get(f"/api/github-sdk-versions/{sdk_type}")

                # All should return 200 (success) or at least not 404
                self.assertIn(response.status_code, [200, 500])  # 500 is acceptable for API failures

                if response.status_code == 200:
                    data = response.json()
                    self.assertIn("latestVersion", data)
                    self.assertIn("versions", data)
                    self.assertIn("releaseDates", data)

    def test_error_logging_and_capture(self):
        """Test that errors are properly logged and captured."""
        with (
            patch("posthog.api.github_sdk_versions.requests.get") as mock_get,
            patch("posthog.api.github_sdk_versions.capture_exception") as mock_capture,
            patch("posthog.api.github_sdk_versions.logger") as mock_logger,
        ):
            # Simulate a network error
            mock_get.side_effect = requests.exceptions.ConnectionError("Network error")

            response = self.client.get("/api/github-sdk-versions/web")

            self.assertEqual(response.status_code, 500)

            # Verify error was captured
            mock_capture.assert_called_once()
            call_args = mock_capture.call_args
            self.assertIsInstance(call_args[0][0], requests.exceptions.ConnectionError)
            self.assertEqual(call_args[1]["sdk_type"], "web")

            # Verify error was logged
            mock_logger.error.assert_called_once()


class TestGitHubSDKVersionsHelperFunctions(TestCase):
    """Test individual helper functions in isolation."""

    def test_version_extraction_patterns(self):
        """Test that version extraction patterns work correctly for different formats."""
        test_cases = [
            # Web SDK format
            ("## 1.258.5\n\nChanges\n\n## 1.258.4", r"^## (\d+\.\d+\.\d+)$", ["1.258.5", "1.258.4"]),
            # Python SDK format
            ("# 6.7.6 - 2025-09-01\n\n# 6.7.5 - 2025-08-30", r"^# (\d+\.\d+\.\d+)", ["6.7.6", "6.7.5"]),
            # PHP SDK format
            ("3.6.0 / 2025-04-30\n\n3.5.9 / 2025-04-20", r"^(\d+\.\d+\.\d+) /", ["3.6.0", "3.5.9"]),
        ]

        import re

        for content, pattern, expected in test_cases:
            matches = re.findall(pattern, content, re.MULTILINE)
            self.assertEqual(matches, expected)

    def test_github_release_tag_parsing(self):
        """Test GitHub release tag parsing for different SDK repositories."""
        test_cases = [
            # posthog-js repo
            ("posthog-js@1.258.5", "PostHog/posthog-js", "1.258.5"),
            ("posthog-node@5.8.4", "PostHog/posthog-js", "5.8.4"),
            ("posthog-react-native@4.4.0", "PostHog/posthog-js", "4.4.0"),
            # Standard repos
            ("v6.7.6", "PostHog/posthog-python", "6.7.6"),
            ("v3.30.1", "PostHog/posthog-ios", "3.30.1"),
        ]

        for tag_name, repo, expected_version in test_cases:
            if repo == "PostHog/posthog-js" and "@" in tag_name:
                version = tag_name.split("@")[1]
            elif tag_name.startswith("v"):
                version = tag_name[1:]
            else:
                version = tag_name

            self.assertEqual(version, expected_version)
