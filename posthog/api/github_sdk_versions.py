import re
import json
import time
from typing import Any, Optional

from django.http import JsonResponse

import requests
import structlog
import posthoganalytics
from rest_framework import exceptions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

# 6 hours to match current client-side caching
GITHUB_SDK_CACHE_EXPIRY = 6 * 60 * 60
# Rate limiting safeguards
MAX_RETRIES = 3
INITIAL_BACKOFF = 1  # seconds


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def github_sdk_versions(request: Request, sdk_type: str) -> JsonResponse:
    """
    Fetch and cache GitHub SDK version data for SDK Doctor.
    Replaces client-side GitHub API calls with server-side caching.
    Protected by sdk-doctor-beta feature flag.
    """
    # Check if user has access to SDK Doctor beta
    if not posthoganalytics.feature_enabled("sdk-doctor-beta", str(request.user.distinct_id)):
        raise exceptions.ValidationError("SDK Doctor is not enabled for this user")

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
        except (json.JSONDecodeError, AttributeError) as e:
            # Cache corrupted, continue to fetch fresh
            logger.warning(f"[SDK Doctor] Cache corrupted for {sdk_type}", error=str(e))
            capture_exception(e)

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
            logger.error(f"[SDK Doctor] No data received from GitHub for {sdk_type}")
            return JsonResponse({"error": "The Doctor is unavailable. Please try again later."}, status=500)
    except Exception as e:
        logger.exception(f"[SDK Doctor] Failed to fetch {sdk_type} data from GitHub")
        capture_exception(e)
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
            logger.error(f"[SDK Doctor] Failed to fetch Web SDK changelog", status_code=changelog_response.status_code)
            return None

        changelog_content = changelog_response.text

        # Parse versions without dates (new format: ## X.Y.Z)
        version_pattern = re.compile(r"^## (\d+\.\d+\.\d+)$", re.MULTILINE)
        versions_no_date = version_pattern.findall(changelog_content)

        # Parse versions WITH dates (old format: ## X.Y.Z - YYYY-MM-DD)
        version_with_date_pattern = re.compile(r"^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})$", re.MULTILINE)
        versions_with_dates = version_with_date_pattern.findall(changelog_content)

        # Combine all versions
        all_versions = versions_no_date

        # Build release dates from CHANGELOG (for older versions)
        changelog_dates = {}
        for version, date in versions_with_dates:
            # Convert YYYY-MM-DD to ISO 8601 timestamp (midnight UTC)
            changelog_dates[version] = f"{date}T00:00:00Z"
            # Also add to all_versions list if not already present
            if version not in all_versions:
                all_versions.append(version)

        if not all_versions:
            logger.error(f"[SDK Doctor] No version matches found in Web SDK changelog")
            return None

        latest_version = all_versions[0]

        # Fetch GitHub release dates (for newer versions)
        github_dates = fetch_github_release_dates("PostHog/posthog-js")

        # Merge: GitHub API dates take precedence (more accurate timestamps), CHANGELOG dates as fallback
        release_dates = {**changelog_dates, **github_dates}

        return {"latestVersion": latest_version, "versions": all_versions, "releaseDates": release_dates}
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
    """Fetch Node.js SDK data from CHANGELOG.md + GitHub releases API"""
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

        # Fetch GitHub release dates (cached at server level, safe from rate limiting)
        release_dates = fetch_github_release_dates("PostHog/posthog-js")

        return {"latestVersion": latest_version, "versions": versions, "releaseDates": release_dates}
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
    """Fetch Go SDK data from CHANGELOG.md + GitHub releases API"""
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

        # Fetch GitHub release dates
        release_dates = fetch_github_release_dates("PostHog/posthog-go")

        return {"latestVersion": latest_version, "versions": versions, "releaseDates": release_dates}
    except Exception:
        return None


def fetch_php_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch PHP SDK data from History.md with release dates"""
    try:
        # Fetch History.md for versions
        changelog_response = requests.get(
            "https://raw.githubusercontent.com/PostHog/posthog-php/master/History.md", timeout=10
        )
        if not changelog_response.ok:
            return None

        changelog_content = changelog_response.text
        # PHP format: 3.6.0 / 2025-04-30
        version_pattern = re.compile(r"^(\d+\.\d+\.\d+) / (\d{4}-\d{2}-\d{2})", re.MULTILINE)
        matches = version_pattern.findall(changelog_content)

        if not matches:
            return None

        latest_version = matches[0][0]
        versions = []
        release_dates = {}
        for version, date in matches:
            versions.append(version)
            release_dates[version] = f"{date}T00:00:00Z"

        return {"latestVersion": latest_version, "versions": versions, "releaseDates": release_dates}
    except Exception:
        return None


def fetch_ruby_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Ruby SDK data from CHANGELOG.md with date parsing from CHANGELOG and PR merge dates"""
    try:
        # Fetch CHANGELOG.md for versions
        changelog_response = requests.get(
            "https://raw.githubusercontent.com/PostHog/posthog-ruby/main/CHANGELOG.md", timeout=10
        )
        if not changelog_response.ok:
            return None

        changelog_content = changelog_response.text

        # Pattern 1: Versions with dates directly in CHANGELOG (## 3.0.1 - 2025-05-20)
        version_with_date_pattern = re.compile(r"^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})$", re.MULTILINE)
        versions_with_dates = version_with_date_pattern.findall(changelog_content)

        # Build release_dates dict from CHANGELOG dates
        release_dates = {}
        for version, date in versions_with_dates:
            release_dates[version] = f"{date}T00:00:00Z"

        # Combine all versions preserving CHANGELOG order
        # Use regex to find all version headers in order
        all_versions_pattern = re.compile(r"^## (\d+\.\d+\.\d+)", re.MULTILINE)
        all_versions = all_versions_pattern.findall(changelog_content)

        if not all_versions:
            return None

        latest_version = all_versions[0]

        # For versions without dates, try to extract PR numbers and fetch merge dates
        # Split changelog into sections by version header
        version_sections = re.split(r"^## (\d+\.\d+\.\d+)", changelog_content, flags=re.MULTILINE)

        for i in range(1, len(version_sections), 2):
            version = version_sections[i]
            content = version_sections[i + 1] if i + 1 < len(version_sections) else ""

            # Skip if we already have a date for this version
            if version in release_dates:
                continue

            # Extract PR number from content (e.g., [#72](https://github.com/PostHog/posthog-ruby/pull/72))
            pr_pattern = re.compile(r"\[#(\d+)\]\(")
            pr_match = pr_pattern.search(content)

            if pr_match:
                pr_number = pr_match.group(1)
                # Fetch merge date from GitHub PR API
                merge_date = fetch_pr_merge_date("PostHog/posthog-ruby", pr_number)
                if merge_date:
                    release_dates[version] = merge_date

        return {"latestVersion": latest_version, "versions": all_versions, "releaseDates": release_dates}
    except Exception:
        return None


def fetch_elixir_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Elixir SDK data from CHANGELOG.md with release dates"""
    try:
        # Fetch CHANGELOG.md for versions
        changelog_response = requests.get(
            "https://raw.githubusercontent.com/PostHog/posthog-elixir/master/CHANGELOG.md", timeout=10
        )
        if not changelog_response.ok:
            return None

        changelog_content = changelog_response.text
        # Elixir format: ## 2.0.0 - 2025-09-30
        version_pattern = re.compile(r"^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})", re.MULTILINE)
        matches = version_pattern.findall(changelog_content)

        if not matches:
            return None

        latest_version = matches[0][0]
        versions = []
        release_dates = {}
        for version, date in matches:
            versions.append(version)
            release_dates[version] = f"{date}T00:00:00Z"

        return {"latestVersion": latest_version, "versions": versions, "releaseDates": release_dates}
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


def fetch_pr_merge_date(repo: str, pr_number: str) -> Optional[str]:
    """
    Fetch PR merge date from GitHub PR API with exponential backoff.
    Returns ISO date string or None if not available.
    """
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(f"https://api.github.com/repos/{repo}/pulls/{pr_number}", timeout=10)

            # Handle rate limiting with exponential backoff (403 or 429)
            if response.status_code in [403, 429]:
                if attempt < MAX_RETRIES - 1:
                    backoff_time = INITIAL_BACKOFF * (2**attempt)
                    logger.warning(
                        f"[SDK Doctor] GitHub API rate limit hit for {repo} PR#{pr_number} (status {response.status_code}), retrying in {backoff_time}s (attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    time.sleep(backoff_time)
                    continue
                else:
                    logger.error(
                        f"[SDK Doctor] GitHub API rate limit exceeded for {repo} PR#{pr_number} after {MAX_RETRIES} attempts (status {response.status_code})"
                    )
                    return None

            if not response.ok:
                logger.warning(f"[SDK Doctor] GitHub API error for {repo} PR#{pr_number}: {response.status_code}")
                return None

            pr_data = response.json()
            merged_at = pr_data.get("merged_at")

            return merged_at
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                backoff_time = INITIAL_BACKOFF * (2**attempt)
                logger.warning(
                    f"[SDK Doctor] Error fetching PR merge date for {repo} PR#{pr_number}, retrying in {backoff_time}s: {str(e)}"
                )
                time.sleep(backoff_time)
                continue
            else:
                logger.exception(
                    f"[SDK Doctor] Failed to fetch PR merge date for {repo} PR#{pr_number} after {MAX_RETRIES} attempts"
                )
                return None

    return None


def fetch_github_release_dates(repo: str) -> dict[str, str]:
    """
    Fetch release dates from GitHub releases API with exponential backoff.
    Returns dict mapping version to ISO date string.
    """
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(f"https://api.github.com/repos/{repo}/releases?per_page=100", timeout=10)

            # Handle rate limiting with exponential backoff (403 or 429)
            if response.status_code in [403, 429]:
                if attempt < MAX_RETRIES - 1:
                    backoff_time = INITIAL_BACKOFF * (2**attempt)
                    logger.warning(
                        f"[SDK Doctor] GitHub API rate limit hit for {repo} (status {response.status_code}), retrying in {backoff_time}s (attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    time.sleep(backoff_time)
                    continue
                else:
                    logger.error(
                        f"[SDK Doctor] GitHub API rate limit exceeded for {repo} after {MAX_RETRIES} attempts (status {response.status_code})"
                    )
                    return {}

            if not response.ok:
                logger.warning(f"[SDK Doctor] GitHub API error for {repo}: {response.status_code}")
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
                ]:
                    # Standard repos: v1.2.3
                    if tag_name.startswith("v"):
                        version = tag_name[1:]
                        release_dates[version] = published_at
                elif repo == "PostHog/posthog-android":
                    # Android monorepo: android-v3.23.0
                    if tag_name.startswith("android-v"):
                        version = tag_name[9:]  # Strip "android-v" prefix
                        release_dates[version] = published_at

            return release_dates
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                backoff_time = INITIAL_BACKOFF * (2**attempt)
                logger.warning(
                    f"[SDK Doctor] Error fetching GitHub releases for {repo}, retrying in {backoff_time}s: {str(e)}"
                )
                time.sleep(backoff_time)
                continue
            else:
                logger.exception(
                    f"[SDK Doctor] Failed to fetch GitHub releases for {repo} after {MAX_RETRIES} attempts"
                )
                return {}

    return {}
