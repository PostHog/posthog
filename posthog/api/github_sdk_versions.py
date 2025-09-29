import re
import json
from typing import Any, Optional

from django.http import JsonResponse

import requests
import structlog
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request

from posthog.redis import get_client

logger = structlog.get_logger(__name__)

# 6 hours to match current client-side caching
GITHUB_SDK_CACHE_EXPIRY = 6 * 60 * 60


@api_view(["GET"])
@permission_classes([AllowAny])
def github_sdk_versions(request: Request, sdk_type: str) -> JsonResponse:
    """
    Fetch and cache GitHub SDK version data for SDK Doctor.
    Replaces client-side GitHub API calls with server-side caching.
    """
    redis_client = get_client()
    cache_key = f"github:sdk_versions:{sdk_type}"

    # Try cache first
    cached_data = redis_client.get(cache_key)
    if cached_data:
        try:
            data = json.loads(cached_data.decode("utf-8") if isinstance(cached_data, bytes) else cached_data)
            data["cached"] = True
            logger.info(f"[SDK Doctor] {sdk_type.title()} SDK details successfully read from server CACHE")
            return JsonResponse(data)
        except (json.JSONDecodeError, AttributeError):
            # Cache corrupted, continue to fetch fresh
            pass

    # Fetch fresh data
    logger.info(f"[SDK Doctor] {sdk_type.title()} SDK info not found in CACHE, querying GitHub API")
    try:
        github_data = fetch_github_data_for_sdk(sdk_type)
        if github_data:
            # Cache the result
            redis_client.setex(cache_key, GITHUB_SDK_CACHE_EXPIRY, json.dumps(github_data))
            github_data["cached"] = False
            logger.info(
                f"[SDK Doctor] {sdk_type.title()} SDK info received from GitHub. CACHED successfully on the server"
            )
            return JsonResponse(github_data)
        else:
            return JsonResponse({"error": "The Doctor is unavailable. Please try again later."}, status=500)
    except Exception:
        return JsonResponse({"error": "The Doctor is unavailable. Please try again later."}, status=500)


def fetch_github_data_for_sdk(sdk_type: str) -> Optional[dict[str, Any]]:
    """
    Fetch GitHub data for specific SDK type.
    Mirrors the existing frontend logic for each SDK.
    """
    if sdk_type == "web":
        return fetch_web_sdk_data()
    elif sdk_type == "python":
        return fetch_python_sdk_data()
    elif sdk_type == "node":
        return fetch_node_sdk_data()
    elif sdk_type == "react-native":
        return fetch_react_native_sdk_data()
    elif sdk_type == "flutter":
        return fetch_flutter_sdk_data()
    elif sdk_type == "ios":
        return fetch_ios_sdk_data()
    elif sdk_type == "android":
        return fetch_android_sdk_data()
    elif sdk_type == "go":
        return fetch_go_sdk_data()
    elif sdk_type == "php":
        return fetch_php_sdk_data()
    elif sdk_type == "ruby":
        return fetch_ruby_sdk_data()
    elif sdk_type == "elixir":
        return fetch_elixir_sdk_data()
    elif sdk_type == "dotnet":
        return fetch_dotnet_sdk_data()
    else:
        return None


def fetch_web_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Web SDK data from CHANGELOG.md + GitHub releases API"""
    try:
        # Fetch CHANGELOG.md for versions
        changelog_response = requests.get(
            "https://raw.githubusercontent.com/PostHog/posthog-js/main/packages/browser/CHANGELOG.md", timeout=10
        )
        if not changelog_response.ok:
            return None

        changelog_content = changelog_response.text
        version_pattern = re.compile(r"^## (\d+\.\d+\.\d+)$", re.MULTILINE)
        matches = version_pattern.findall(changelog_content)

        if not matches:
            return None

        latest_version = matches[0]
        versions = matches

        # Fetch GitHub release dates
        release_dates = fetch_github_release_dates("PostHog/posthog-js")

        return {"latestVersion": latest_version, "versions": versions, "releaseDates": release_dates}
    except Exception:
        return None


def fetch_python_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Python SDK data from CHANGELOG.md + GitHub releases API"""
    try:
        # Fetch CHANGELOG.md for versions (Python SDK uses master branch, not main)
        changelog_response = requests.get(
            "https://raw.githubusercontent.com/PostHog/posthog-python/master/CHANGELOG.md", timeout=10
        )
        if not changelog_response.ok:
            return None

        changelog_content = changelog_response.text
        # Python SDK uses single # for version headers: # 6.7.6 - 2025-09-16
        version_pattern = re.compile(r"^# (\d+\.\d+\.\d+)", re.MULTILINE)
        matches = version_pattern.findall(changelog_content)

        if not matches:
            return None

        latest_version = matches[0]
        versions = matches

        # Fetch GitHub release dates
        release_dates = fetch_github_release_dates("PostHog/posthog-python")

        return {"latestVersion": latest_version, "versions": versions, "releaseDates": release_dates}
    except Exception:
        return None


def fetch_node_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Node.js SDK data from CHANGELOG.md (simplified logic)"""
    try:
        # Fetch CHANGELOG.md for versions
        changelog_response = requests.get(
            "https://raw.githubusercontent.com/PostHog/posthog-js/main/packages/node/CHANGELOG.md", timeout=10
        )
        if not changelog_response.ok:
            return None

        changelog_content = changelog_response.text
        version_pattern = re.compile(r"^## (\d+\.\d+\.\d+)$", re.MULTILINE)
        matches = version_pattern.findall(changelog_content)

        if not matches:
            return None

        latest_version = matches[0]
        versions = matches

        return {"latestVersion": latest_version, "versions": versions, "releaseDates": {}}
    except Exception:
        return None


def fetch_react_native_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch React Native SDK data from CHANGELOG.md + GitHub releases API"""
    try:
        # Fetch CHANGELOG.md for versions
        changelog_response = requests.get(
            "https://raw.githubusercontent.com/PostHog/posthog-js/main/packages/react-native/CHANGELOG.md", timeout=10
        )
        if not changelog_response.ok:
            return None

        changelog_content = changelog_response.text
        version_pattern = re.compile(r"^## (\d+\.\d+\.\d+)$", re.MULTILINE)
        matches = version_pattern.findall(changelog_content)

        if not matches:
            return None

        latest_version = matches[0]
        versions = matches

        # Fetch GitHub release dates
        release_dates = fetch_github_release_dates("PostHog/posthog-js")

        return {"latestVersion": latest_version, "versions": versions, "releaseDates": release_dates}
    except Exception:
        return None


def fetch_flutter_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Flutter SDK data from CHANGELOG.md + GitHub releases API"""
    try:
        # Fetch CHANGELOG.md for versions
        changelog_response = requests.get(
            "https://raw.githubusercontent.com/PostHog/posthog-flutter/main/CHANGELOG.md", timeout=10
        )
        if not changelog_response.ok:
            return None

        changelog_content = changelog_response.text
        version_pattern = re.compile(r"^## (\d+\.\d+\.\d+)$", re.MULTILINE)
        matches = version_pattern.findall(changelog_content)

        if not matches:
            return None

        latest_version = matches[0]
        versions = matches

        # Fetch GitHub release dates
        release_dates = fetch_github_release_dates("PostHog/posthog-flutter")

        return {"latestVersion": latest_version, "versions": versions, "releaseDates": release_dates}
    except Exception:
        return None


def fetch_ios_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch iOS SDK data from CHANGELOG.md + GitHub releases API"""
    try:
        # Fetch CHANGELOG.md for versions
        changelog_response = requests.get(
            "https://raw.githubusercontent.com/PostHog/posthog-ios/main/CHANGELOG.md", timeout=10
        )
        if not changelog_response.ok:
            return None

        changelog_content = changelog_response.text
        # iOS format: ## 3.30.1 - 2025-08-12 (skip "## Next" section)
        version_pattern = re.compile(r"^## (\d+\.\d+\.\d+) - \d{4}-\d{2}-\d{2}$", re.MULTILINE)
        matches = version_pattern.findall(changelog_content)

        if not matches:
            return None

        latest_version = matches[0]
        versions = matches

        # Fetch GitHub release dates
        release_dates = fetch_github_release_dates("PostHog/posthog-ios")

        return {"latestVersion": latest_version, "versions": versions, "releaseDates": release_dates}
    except Exception:
        return None


def fetch_android_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Android SDK data from CHANGELOG.md + GitHub releases API"""
    try:
        # Fetch CHANGELOG.md for versions
        changelog_response = requests.get(
            "https://raw.githubusercontent.com/PostHog/posthog-android/main/posthog-android/CHANGELOG.md", timeout=10
        )
        if not changelog_response.ok:
            return None

        changelog_content = changelog_response.text
        # Android format: ## 3.20.2 - 2025-08-07
        version_pattern = re.compile(r"^## (\d+\.\d+\.\d+)", re.MULTILINE)
        matches = version_pattern.findall(changelog_content)

        if not matches:
            return None

        latest_version = matches[0]
        versions = matches

        # Fetch GitHub release dates
        release_dates = fetch_github_release_dates("PostHog/posthog-android")

        return {"latestVersion": latest_version, "versions": versions, "releaseDates": release_dates}
    except Exception:
        return None


def fetch_go_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Go SDK data from CHANGELOG.md (simplified logic)"""
    try:
        # Fetch CHANGELOG.md for versions (Go SDK uses master branch, not main)
        changelog_response = requests.get(
            "https://raw.githubusercontent.com/PostHog/posthog-go/master/CHANGELOG.md", timeout=10
        )
        if not changelog_response.ok:
            return None

        changelog_content = changelog_response.text
        version_pattern = re.compile(r"^## (\d+\.\d+\.\d+)$", re.MULTILINE)
        matches = version_pattern.findall(changelog_content)

        if not matches:
            return None

        latest_version = matches[0]
        versions = matches

        return {"latestVersion": latest_version, "versions": versions, "releaseDates": {}}
    except Exception:
        return None


def fetch_php_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch PHP SDK data from History.md (simplified logic)"""
    try:
        # Fetch History.md for versions
        changelog_response = requests.get(
            "https://raw.githubusercontent.com/PostHog/posthog-php/master/History.md", timeout=10
        )
        if not changelog_response.ok:
            return None

        changelog_content = changelog_response.text
        # PHP format: 3.6.0 / 2025-04-30
        version_pattern = re.compile(r"^(\d+\.\d+\.\d+) /", re.MULTILINE)
        matches = version_pattern.findall(changelog_content)

        if not matches:
            return None

        latest_version = matches[0]
        versions = matches

        return {"latestVersion": latest_version, "versions": versions, "releaseDates": {}}
    except Exception:
        return None


def fetch_ruby_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Ruby SDK data from CHANGELOG.md (simplified logic)"""
    try:
        # Fetch CHANGELOG.md for versions
        changelog_response = requests.get(
            "https://raw.githubusercontent.com/PostHog/posthog-ruby/main/CHANGELOG.md", timeout=10
        )
        if not changelog_response.ok:
            return None

        changelog_content = changelog_response.text
        version_pattern = re.compile(r"^## (\d+\.\d+\.\d+)$", re.MULTILINE)
        matches = version_pattern.findall(changelog_content)

        if not matches:
            return None

        latest_version = matches[0]
        versions = matches

        return {"latestVersion": latest_version, "versions": versions, "releaseDates": {}}
    except Exception:
        return None


def fetch_elixir_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Elixir SDK data from CHANGELOG.md (simplified logic)"""
    try:
        # Fetch CHANGELOG.md for versions
        changelog_response = requests.get(
            "https://raw.githubusercontent.com/PostHog/posthog-elixir/master/CHANGELOG.md", timeout=10
        )
        if not changelog_response.ok:
            return None

        changelog_content = changelog_response.text
        # Elixir format: ## 1.1.0 - 2025-07-01
        version_pattern = re.compile(r"^## (\d+\.\d+\.\d+)", re.MULTILINE)
        matches = version_pattern.findall(changelog_content)

        if not matches:
            return None

        latest_version = matches[0]
        versions = matches

        return {"latestVersion": latest_version, "versions": versions, "releaseDates": {}}
    except Exception:
        return None


def fetch_dotnet_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch .NET SDK data from GitHub releases API (simplified logic)"""
    try:
        # Fetch GitHub releases for versions
        response = requests.get("https://api.github.com/repos/PostHog/posthog-dotnet/releases?per_page=4", timeout=10)
        if not response.ok:
            return None

        releases = response.json()
        if not releases:
            return None

        # Extract versions from tag names
        versions = []
        for release in releases:
            tag_name = release.get("tag_name", "")
            if tag_name.startswith("v"):
                version = tag_name[1:]  # Remove 'v' prefix
                versions.append(version)

        if not versions:
            return None

        latest_version = versions[0]

        return {"latestVersion": latest_version, "versions": versions, "releaseDates": {}}
    except Exception:
        return None


def fetch_github_release_dates(repo: str) -> dict[str, str]:
    """
    Fetch release dates from GitHub releases API.
    Returns dict mapping version to ISO date string.
    """
    try:
        response = requests.get(f"https://api.github.com/repos/{repo}/releases?per_page=4", timeout=10)
        if not response.ok:
            return {}

        releases = response.json()
        release_dates = {}

        for release in releases:
            tag_name = release.get("tag_name", "")
            published_at = release.get("published_at", "")

            if not tag_name or not published_at:
                continue

            # Extract version from tag name based on repo patterns
            if repo == "PostHog/posthog-js":
                # Web SDK: posthog-js@1.258.5
                # Node SDK: posthog-node@5.8.4
                # React Native: posthog-react-native@4.4.0
                if "@" in tag_name:
                    version = tag_name.split("@")[1]
                    release_dates[version] = published_at
            elif repo in [
                "PostHog/posthog-python",
                "PostHog/posthog-flutter",
                "PostHog/posthog-ios",
                "PostHog/posthog-android",
            ]:
                # Standard repos: v1.2.3
                if tag_name.startswith("v"):
                    version = tag_name[1:]
                    release_dates[version] = published_at

        return release_dates
    except Exception:
        return {}
