import re
import json
import time
from collections.abc import Callable
from typing import Any, Literal, Optional, cast

import dagster
import requests
import structlog

from posthog.exceptions_capture import capture_exception

from dags.common import JobOwners, redis

logger = structlog.get_logger(__name__)

CACHE_EXPIRY = 60 * 60 * 24 * 7  # 7 days
MAX_REQUEST_RETRIES = 3
INITIAL_RETRIES_BACKOFF = 1  # in seconds

SdkTypes = Literal[
    "web",
    "posthog-ios",
    "posthog-android",
    "posthog-node",
    "posthog-python",
    "posthog-php",
    "posthog-ruby",
    "posthog-go",
    "posthog-flutter",
    "posthog-react-native",
    "posthog-dotnet",
    "posthog-elixir",
]
SDK_TYPES: list[SdkTypes] = [
    "web",
    "posthog-ios",
    "posthog-android",
    "posthog-node",
    "posthog-python",
    "posthog-php",
    "posthog-ruby",
    "posthog-go",
    "posthog-flutter",
    "posthog-react-native",
    "posthog-dotnet",
    "posthog-elixir",
]


# Using lambda here to be able to define this before defining the functions
SDK_FETCH_FUNCTIONS: dict[SdkTypes, Callable[[], Optional[dict[str, Any]]]] = {
    "web": lambda: fetch_web_sdk_data(),
    "posthog-python": lambda: fetch_python_sdk_data(),
    "posthog-node": lambda: fetch_node_sdk_data(),
    "posthog-react-native": lambda: fetch_react_native_sdk_data(),
    "posthog-flutter": lambda: fetch_flutter_sdk_data(),
    "posthog-ios": lambda: fetch_ios_sdk_data(),
    "posthog-android": lambda: fetch_android_sdk_data(),
    "posthog-go": lambda: fetch_go_sdk_data(),
    "posthog-php": lambda: fetch_php_sdk_data(),
    "posthog-ruby": lambda: fetch_ruby_sdk_data(),
    "posthog-elixir": lambda: fetch_elixir_sdk_data(),
    "posthog-dotnet": lambda: fetch_dotnet_sdk_data(),
}


def fetch_github_data_for_sdk(lib_name: str) -> Optional[dict[str, Any]]:
    """Fetch GitHub data for specific SDK type using ClickHouse $lib value."""
    fetch_fn = SDK_FETCH_FUNCTIONS.get(cast(SdkTypes, lib_name))
    if fetch_fn:
        return fetch_fn()
    return None


def fetch_sdk_data_from_releases(repo: str, tag_prefix: str = "") -> Optional[dict[str, Any]]:
    """Helper function to fetch SDK data from GitHub releases API."""
    try:
        response = requests.get(f"https://api.github.com/repos/{repo}/releases", timeout=10)
        if not response.ok:
            logger.error(f"[SDK Doctor] Failed to fetch releases for {repo}", status_code=response.status_code)
            return None

        releases = response.json()
        if not releases:
            return None

        latest_version = None
        release_dates = {}

        for release in releases:
            if release.get("draft") or release.get("prerelease"):
                continue

            tag = release.get("tag_name", "")

            # If tag_prefix is specified, only process tags that match
            if tag_prefix:
                if not tag.startswith(tag_prefix):
                    continue
                version = tag[len(tag_prefix) :]
            elif tag.startswith("v"):
                version = tag[1:]
            elif tag.startswith("android-v"):
                version = tag[9:]
            else:
                version = tag

            if version:
                if latest_version is None:
                    latest_version = version
                published_at = release.get("published_at")
                if published_at:
                    release_dates[version] = published_at

        if not latest_version:
            return None

        return {"latestVersion": latest_version, "releaseDates": release_dates}
    except Exception as e:
        logger.exception(f"[SDK Doctor] Failed to fetch SDK data from releases for {repo}")
        capture_exception(e)
        return None


def fetch_web_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Web SDK data from GitHub releases API"""
    return fetch_sdk_data_from_releases("PostHog/posthog-js", tag_prefix="posthog-js@")


def fetch_python_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Python SDK data from GitHub releases API"""
    return fetch_sdk_data_from_releases("PostHog/posthog-python", tag_prefix="v")


def fetch_node_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Node.js SDK data from GitHub releases API"""
    return fetch_sdk_data_from_releases("PostHog/posthog-js", tag_prefix="posthog-node@")


def fetch_react_native_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch React Native SDK data from GitHub releases API"""
    return fetch_sdk_data_from_releases("PostHog/posthog-js", tag_prefix="posthog-react-native@")


def fetch_flutter_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Flutter SDK data from GitHub releases API"""
    return fetch_sdk_data_from_releases("PostHog/posthog-flutter")


def fetch_ios_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch iOS SDK data from GitHub releases API"""
    return fetch_sdk_data_from_releases("PostHog/posthog-ios")


def fetch_android_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Android SDK data from GitHub releases API"""
    return fetch_sdk_data_from_releases("PostHog/posthog-android", tag_prefix="android-v")


def fetch_go_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Go SDK data from GitHub releases API"""
    return fetch_sdk_data_from_releases("PostHog/posthog-go", tag_prefix="v")


def fetch_php_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch PHP SDK data from History.md with release dates"""
    try:
        changelog_response = requests.get(
            "https://raw.githubusercontent.com/PostHog/posthog-php/master/History.md", timeout=10
        )
        if not changelog_response.ok:
            return None

        changelog_content = changelog_response.text
        version_pattern = re.compile(r"^(\d+\.\d+\.\d+) / (\d{4}-\d{2}-\d{2})", re.MULTILINE)
        matches = version_pattern.findall(changelog_content)

        if not matches:
            return None

        latest_version = matches[0][0]
        release_dates = {}
        for version, date in matches:
            release_dates[version] = f"{date}T00:00:00Z"

        return {"latestVersion": latest_version, "releaseDates": release_dates}
    except Exception:
        return None


def fetch_ruby_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Ruby SDK data from CHANGELOG.md with release dates"""
    try:
        changelog_response = requests.get(
            "https://raw.githubusercontent.com/PostHog/posthog-ruby/main/CHANGELOG.md", timeout=10
        )
        if not changelog_response.ok:
            return None

        changelog_content = changelog_response.text
        version_pattern = re.compile(r"^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})", re.MULTILINE)
        matches = version_pattern.findall(changelog_content)

        if not matches:
            return None

        latest_version = matches[0][0]
        release_dates = {}
        for version, date in matches:
            release_dates[version] = f"{date}T00:00:00Z"

        return {"latestVersion": latest_version, "releaseDates": release_dates}
    except Exception:
        return None


def fetch_elixir_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch Elixir SDK data from CHANGELOG.md with release dates"""
    try:
        changelog_response = requests.get(
            "https://raw.githubusercontent.com/PostHog/posthog-elixir/master/CHANGELOG.md", timeout=10
        )
        if not changelog_response.ok:
            return None

        changelog_content = changelog_response.text
        version_pattern = re.compile(r"^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})", re.MULTILINE)
        matches = version_pattern.findall(changelog_content)

        if not matches:
            return None

        latest_version = matches[0][0]
        release_dates = {}
        for version, date in matches:
            release_dates[version] = f"{date}T00:00:00Z"

        return {"latestVersion": latest_version, "releaseDates": release_dates}
    except Exception:
        return None


def fetch_dotnet_sdk_data() -> Optional[dict[str, Any]]:
    """Fetch .NET SDK data from GitHub releases API"""
    return fetch_sdk_data_from_releases("PostHog/posthog-dotnet", tag_prefix="v")


def fetch_github_release_dates(repo: str) -> dict[str, str]:
    """Fetch release dates from GitHub releases API with exponential backoff."""
    for attempt in range(MAX_REQUEST_RETRIES):
        try:
            response = requests.get(f"https://api.github.com/repos/{repo}/releases?per_page=100", timeout=10)

            if response.status_code in [403, 429]:
                if attempt < MAX_REQUEST_RETRIES - 1:
                    backoff_time = INITIAL_RETRIES_BACKOFF * (2**attempt)
                    logger.warning(
                        f"[SDK Doctor] GitHub API rate limit hit for {repo} (status {response.status_code}), retrying in {backoff_time}s (attempt {attempt + 1}/{MAX_REQUEST_RETRIES})"
                    )
                    time.sleep(backoff_time)
                    continue
                else:
                    logger.error(
                        f"[SDK Doctor] GitHub API rate limit exceeded for {repo} after {MAX_REQUEST_RETRIES} attempts (status {response.status_code})"
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

                if repo == "PostHog/posthog-js":
                    if "@" in tag_name:
                        version = tag_name.split("@")[1]
                        release_dates[version] = published_at
                elif repo in [
                    "PostHog/posthog-python",
                    "PostHog/posthog-flutter",
                    "PostHog/posthog-ios",
                    "PostHog/posthog-go",
                    "PostHog/posthog-dotnet",
                ]:
                    if tag_name.startswith("v"):
                        version = tag_name[1:]
                        release_dates[version] = published_at
                elif repo == "PostHog/posthog-android":
                    if tag_name.startswith("android-v"):
                        version = tag_name[9:]
                        release_dates[version] = published_at

            return release_dates
        except Exception as e:
            if attempt < MAX_REQUEST_RETRIES - 1:
                backoff_time = INITIAL_RETRIES_BACKOFF * (2**attempt)
                logger.warning(
                    f"[SDK Doctor] Error fetching GitHub releases for {repo}, retrying in {backoff_time}s: {str(e)}"
                )
                time.sleep(backoff_time)
                continue
            else:
                logger.exception(
                    f"[SDK Doctor] Failed to fetch GitHub releases for {repo} after {MAX_REQUEST_RETRIES} attempts"
                )
                return {}

    return {}


# ---- Dagster defs
retry_policy = dagster.RetryPolicy(
    max_retries=3,
    delay=1,
    backoff=dagster.Backoff.EXPONENTIAL,
    jitter=dagster.Jitter.FULL,
)


@dagster.op(retry_policy=retry_policy)
def fetch_github_sdk_versions_op(context: dagster.OpExecutionContext) -> dict[str, Optional[dict[str, Any]]]:
    """Fetch GitHub SDK version data for all SDK types."""
    sdk_data = {}
    fetched_count = 0
    failed_count = 0

    for lib_name in SDK_TYPES:
        try:
            context.log.info(f"Fetching {lib_name} SDK data from GitHub")
            github_data = fetch_github_data_for_sdk(lib_name)

            if github_data:
                sdk_data[lib_name] = github_data
                fetched_count += 1
                context.log.info(f"Successfully fetched {lib_name} SDK data")
            else:
                failed_count += 1
                context.log.warning(f"No data received from GitHub for {lib_name}")
        except Exception as e:
            failed_count += 1
            context.log.exception(f"Failed to fetch {lib_name} SDK data")
            capture_exception(e)

    context.log.info(f"Fetched {fetched_count} SDK versions")
    context.log.info(f"Failed to fetch {failed_count} SDK versions")
    context.log.info(f"Total SDKs: {len(SDK_TYPES)}")
    context.log.info(f"SDK data: {sdk_data}")

    context.add_output_metadata(
        {
            "fetched_count": dagster.MetadataValue.int(fetched_count),
            "failed_count": dagster.MetadataValue.int(failed_count),
            "total_sdks": dagster.MetadataValue.int(len(SDK_TYPES)),
        }
    )

    return sdk_data  # type: ignore


@dagster.op(retry_policy=retry_policy)
def cache_github_sdk_versions_op(
    context: dagster.OpExecutionContext,
    sdk_data: dict[str, Optional[dict[str, Any]]],
    redis_client: dagster.ResourceParam[redis.Redis],
) -> None:
    """Cache GitHub SDK version data to Redis."""
    cached_count = 0
    skipped_count = 0

    for lib_name, github_data in sdk_data.items():
        if github_data is None:
            skipped_count += 1
            continue

        cache_key = f"github:sdk_versions:{lib_name}"
        try:
            redis_client.setex(cache_key, CACHE_EXPIRY, json.dumps(github_data))
            cached_count += 1
            context.log.info(f"Successfully cached {lib_name} SDK data")
        except Exception as e:
            context.log.exception(f"Failed to cache {lib_name} SDK data")
            capture_exception(e)

    context.log.info(f"Cached {cached_count} SDK versions")
    context.log.info(f"Skipped {skipped_count} SDK versions")
    context.log.info(f"Total SDKs: {len(sdk_data)}")
    context.log.info(f"SDK data: {sdk_data}")

    context.add_output_metadata(
        {
            "cached_count": dagster.MetadataValue.int(cached_count),
            "skipped_count": dagster.MetadataValue.int(skipped_count),
            "total_sdks": dagster.MetadataValue.int(len(sdk_data)),
        }
    )


@dagster.job(
    description="Queries GitHub for most recent SDK versions and caches them in Redis",
    tags={"owner": JobOwners.TEAM_GROWTH.value},
)
def cache_github_sdk_versions_job():
    sdk_data = fetch_github_sdk_versions_op()
    cache_github_sdk_versions_op(sdk_data)


cache_github_sdk_versions_schedule = dagster.ScheduleDefinition(
    job=cache_github_sdk_versions_job,
    cron_schedule="0 0 * * *",  # Every day at midnight
    execution_timezone="UTC",
    name="cache_github_sdk_versions_schedule",
)
