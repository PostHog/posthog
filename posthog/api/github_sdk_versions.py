import re
import json
import time
from typing import cast

from django.http import JsonResponse

import requests
import structlog
import posthoganalytics
from rest_framework import exceptions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from posthog.exceptions_capture import capture_exception
from posthog.models.user import User
from posthog.redis import get_client

from dags.sdk_doctor.github_sdk_versions import SDK_TYPES

logger = structlog.get_logger(__name__)

# SDK to GitHub repo mapping for lazy-loading individual version dates
SDK_REPO_MAP = {
    "web": ("PostHog/posthog-js", "posthog-js@{version}"),
    "posthog-node": ("PostHog/posthog-js", "posthog-node@{version}"),
    "posthog-react-native": ("PostHog/posthog-js", "posthog-react-native@{version}"),
    "posthog-python": ("PostHog/posthog-python", "v{version}"),
    "posthog-flutter": ("PostHog/posthog-flutter", "{version}"),
    "posthog-ios": ("PostHog/posthog-ios", "{version}"),
    "posthog-android": ("PostHog/posthog-android", "android-v{version}"),
    "posthog-go": ("PostHog/posthog-go", "v{version}"),
    "posthog-php": ("PostHog/posthog-php", "v{version}"),
    "posthog-ruby": ("PostHog/posthog-ruby", "v{version}"),
    "posthog-elixir": ("PostHog/posthog-elixir", "v{version}"),
    "posthog-dotnet": ("PostHog/posthog-dotnet", "v{version}"),
}

# Fallback tag formats for SDKs with legacy versions
# Old posthog-js versions used v-prefixed tags (e.g., "v1.187.2")
FALLBACK_TAG_TEMPLATES = {
    "web": "v{version}",  # Legacy format: v-prefixed (e.g., v1.187.2)
}

# CHANGELOG paths for monorepo SDKs with pre-monorepo history
CHANGELOG_PATHS = {
    "posthog-node": "packages/node/CHANGELOG.md",
    "posthog-react-native": "packages/react-native/CHANGELOG.md",
}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def github_sdk_versions(request: Request) -> JsonResponse:
    """
    Serve cached GitHub SDK version data for SDK Doctor.
    Data is cached by Dagster job that runs daily at midnight UTC.
    Protected by sdk-doctor-beta feature flag.
    """
    user = cast(User, request.user)
    if not posthoganalytics.feature_enabled("sdk-doctor-beta", str(user.distinct_id)):
        raise exceptions.ValidationError("SDK Doctor is not enabled for this user")

    redis_client = get_client()
    response = {}
    for sdk_type in SDK_TYPES:
        cache_key = f"github:sdk_versions:{sdk_type}"
        cached_data = redis_client.get(cache_key)
        if cached_data:
            try:
                data = json.loads(cached_data.decode("utf-8") if isinstance(cached_data, bytes) else cached_data)
                # cachedAt is now stored in the cache data itself (no need to calculate from TTL)
                response[sdk_type] = data
            except (json.JSONDecodeError, AttributeError) as e:
                logger.warning(f"[SDK Doctor] Cache corrupted for {sdk_type}", error=str(e))
                capture_exception(e, {"sdk_type": sdk_type, "cache_key": cache_key})
        else:
            logger.warning(f"[SDK Doctor] {sdk_type} SDK info not found in cache")
            response[sdk_type] = {"error": "SDK data not available. Please try again later."}

    return JsonResponse(response)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sdk_version_date(request: Request, sdk_type: str, version: str) -> JsonResponse:
    """
    Lazy-load release dates for versions not in main cache.
    Fetches from GitHub on-demand and caches permanently (release dates are immutable).
    """
    user = cast(User, request.user)
    if not posthoganalytics.feature_enabled("sdk-doctor-beta", str(user.distinct_id)):
        raise exceptions.ValidationError("SDK Doctor is not enabled for this user")

    # Validate SDK type
    if sdk_type not in SDK_REPO_MAP:
        raise exceptions.ValidationError(f"Invalid SDK type: {sdk_type}")

    redis_client = get_client()
    cache_key = f"github:sdk_version_date:{sdk_type}:{version}"

    # Check cache first
    cached_date = redis_client.get(cache_key)
    if cached_date:
        try:
            return JsonResponse(
                {
                    "releaseDate": cached_date.decode("utf-8") if isinstance(cached_date, bytes) else cached_date,
                    "cached": True,
                }
            )
        except (AttributeError, UnicodeDecodeError) as e:
            logger.warning(f"[SDK Doctor] Cache corrupted for {sdk_type}@{version}", error=str(e))
            capture_exception(e, {"sdk_type": sdk_type, "version": version, "cache_key": cache_key})

    # Fetch from GitHub API with retry for rate limits
    repo, tag_template = SDK_REPO_MAP[sdk_type]
    tag_name = tag_template.format(version=version)

    try:
        github_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag_name}"
        response = requests.get(github_url, timeout=10)

        if response.status_code in [403, 429]:
            logger.warning(
                f"[SDK Doctor] GitHub API rate limit hit for {sdk_type}@{version} (status {response.status_code}), retrying after 2s"
            )
            time.sleep(2)
            response = requests.get(github_url, timeout=10)

        if response.status_code in [403, 429]:
            logger.error(
                f"[SDK Doctor] GitHub API rate limit exceeded for {sdk_type}@{version} after retry (status {response.status_code})"
            )
            return JsonResponse({"error": "GitHub API rate limit exceeded. Please try again later."}, status=503)

        if response.status_code == 200:
            release_data = response.json()
            release_date = release_data.get("published_at")

            if release_date:
                # Permanent cache (immutable data)
                redis_client.set(cache_key, release_date)
                logger.info(f"[SDK Doctor] Lazy-loaded date for {sdk_type}@{version}: {release_date}")
                return JsonResponse({"releaseDate": release_date, "cached": False})

        # Try fallback tag format for legacy versions
        elif response.status_code == 404 and sdk_type in FALLBACK_TAG_TEMPLATES:
            fallback_tag = FALLBACK_TAG_TEMPLATES[sdk_type].format(version=version)
            fallback_url = f"https://api.github.com/repos/{repo}/releases/tags/{fallback_tag}"

            logger.info(f"[SDK Doctor] Trying fallback tag format for {sdk_type}@{version}: {fallback_tag}")
            fallback_response = requests.get(fallback_url, timeout=10)

            if fallback_response.status_code in [403, 429]:
                logger.warning(
                    f"[SDK Doctor] GitHub API rate limit hit on fallback for {sdk_type}@{version} (status {fallback_response.status_code}), retrying after 2s"
                )
                time.sleep(2)
                fallback_response = requests.get(fallback_url, timeout=10)

            if fallback_response.status_code in [403, 429]:
                logger.error(
                    f"[SDK Doctor] GitHub API rate limit exceeded on fallback for {sdk_type}@{version} after retry (status {fallback_response.status_code})"
                )
                return JsonResponse({"error": "GitHub API rate limit exceeded. Please try again later."}, status=503)

            if fallback_response.status_code == 200:
                release_data = fallback_response.json()
                release_date = release_data.get("published_at")

                if release_date:
                    # Permanent cache (immutable data)
                    redis_client.set(cache_key, release_date)
                    logger.info(
                        f"[SDK Doctor] Lazy-loaded date for {sdk_type}@{version} using fallback tag: {release_date}"
                    )
                    return JsonResponse({"releaseDate": release_date, "cached": False})

        # Try CHANGELOG fallback for monorepo SDKs with pre-monorepo history
        if response.status_code == 404 and sdk_type in CHANGELOG_PATHS:
            changelog_path = CHANGELOG_PATHS[sdk_type]
            changelog_url = f"https://raw.githubusercontent.com/{repo}/main/{changelog_path}"

            logger.info(f"[SDK Doctor] Trying CHANGELOG fallback for {sdk_type}@{version}")
            changelog_response = requests.get(changelog_url, timeout=10)

            if changelog_response.status_code == 200:
                changelog_content = changelog_response.text
                version_pattern = re.compile(r"^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})", re.MULTILINE)
                matches = version_pattern.findall(changelog_content)

                for found_version, date in matches:
                    if found_version == version:
                        release_date = f"{date}T00:00:00Z"
                        redis_client.set(cache_key, release_date)
                        logger.info(
                            f"[SDK Doctor] Lazy-loaded date for {sdk_type}@{version} from CHANGELOG: {release_date}"
                        )
                        return JsonResponse({"releaseDate": release_date, "cached": False})

        logger.warning(
            f"[SDK Doctor] Could not fetch release date for {sdk_type}@{version}", status=response.status_code
        )
        return JsonResponse({"error": "Release date not available"}, status=404)

    except Exception as e:
        logger.exception(f"[SDK Doctor] Error fetching release date for {sdk_type}@{version}")
        capture_exception(e, {"sdk_type": sdk_type, "version": version})
        return JsonResponse({"error": "Failed to fetch release date"}, status=500)
