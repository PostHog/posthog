import json
from datetime import datetime, timedelta, date
from typing import Optional

from rest_framework import request, response, viewsets

from posthog import redis
from posthog.api.utils import action
import requests
from posthog.schema import SDKUsageData, SDKWarning, Level, SDKDeprecationWarningsResponse

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.helpers.version_utils import diff_versions, is_equal_version, version_to_string
from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.rate_limit import (
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
)


LIBRARIES = [
    {
        "lib": "web",
        "tagsUrl": "https://api.github.com/repos/posthog/posthog-js/tags",
        "deprecationUrl": "https://raw.githubusercontent.com/PostHog/posthog-js/main/deprecation.json",
    },
    {
        "lib": "posthog-python",
        "tagsUrl": "https://api.github.com/repos/posthog/posthog-python/tags",
    },
    {
        "lib": "posthog-react-native",
        # TODO: handle the tags url being shared between a few different JS SDKs
        # "tagsUrl": "https://api.github.com/repos/posthog/posthog-js-lite/tags",
    },
    {
        "lib": "posthog-node",
        # TODO: handle the tags url being shared between a few different JS SDKs
        # "tagsUrl": "https://api.github.com/repos/posthog/posthog-js-lite/tags",
    },
    {
        "lib": "js",  # lite
        # TODO: handle the tags url being shared between a few different JS SDKs
        # "tagsUrl": "https://api.github.com/repos/posthog/posthog-js-lite/tags",
    },
    {
        "lib": "posthog-ruby",
        "tagsUrl": "https://api.github.com/repos/PostHog/posthog-ruby/tags",
    },
    {
        "lib": "posthog-ios",
        "tagsUrl": "https://api.github.com/repos/PostHog/posthog-ios/tags",
    },
    {
        "lib": "posthog-android",
        "tagsUrl": "https://api.github.com/repos/PostHog/posthog-android/tags",
    },
    {
        "lib": "posthog-go",
        "tagsUrl": "https://api.github.com/repos/PostHog/posthog-go/tags",
    },
    {
        "lib": "posthog-php",
        "tagsUrl": "https://api.github.com/repos/PostHog/posthog-php/tags",
    },
    {
        "lib": "posthog-flutter",
        "tagsUrl": "https://api.github.com/repos/PostHog/posthog-flutter/tags",
    },
    {
        "lib": "posthog-java",
        "tagsUrl": "https://api.github.com/repos/PostHog/posthog-java/tags",
    },
    {
        "lib": "posthog-rs",
        "tagsUrl": "https://api.github.com/repos/PostHog/posthog-rs/tags",
    },
    {
        "lib": "posthog-dotnet",
        "tagsUrl": "https://api.github.com/repos/PostHog/posthog-dotnet/tags",
    },
    {
        "lib": "posthog-elixir",
        "tagsUrl": "https://api.github.com/repos/PostHog/posthog-elixir/tags",
    },
]

TAGS_CACHE_KEY_PREFIX = "@posthog/sdk-tags/"
DEPRECATION_CACHE_KEY_PREFIX = "@posthog/sdk-deprecation/"
SDK_USAGE_CACHE_KEY_PREFIX = "@posthog/sdk-usage/"
CACHE_TTL = 5 * 60  # 5 minutes in seconds
CURRENT_DAY_TTL = 60 * 60  # 1 hour in seconds
HISTORICAL_TTL = 7 * 24 * 60 * 60  # 7 days in seconds


def get_tags(lib_name: str, tags_url: str) -> Optional[list]:
    """Get tags data for a specific library with caching"""
    cache_key = f"{TAGS_CACHE_KEY_PREFIX}{lib_name}"
    redis_client = redis.get_client()

    # Try to get from cache first
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    # If not in cache, fetch from GitHub API
    try:
        response = requests.get(tags_url)
        if response.status_code == 200:
            versions = [tag["name"].lstrip("v") for tag in response.json()]
            redis_client.set(cache_key, json.dumps(versions), ex=CACHE_TTL)
            return versions
    except Exception:
        pass

    return None


def get_deprecation(lib_name: str, deprecation_url: str) -> Optional[dict]:
    """Get deprecation data for a specific library with caching"""
    cache_key = f"{DEPRECATION_CACHE_KEY_PREFIX}{lib_name}"
    redis_client = redis.get_client()

    # Try to get from cache first
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    # If not in cache, fetch from GitHub
    try:
        response = requests.get(deprecation_url)
        if response.status_code == 200:
            deprecation_data = response.json()
            redis_client.set(cache_key, json.dumps(deprecation_data), ex=CACHE_TTL)
            return deprecation_data
    except Exception:
        pass

    return None


class SdkDeprecationWarningsViewSet(
    TeamAndOrgViewSetMixin,
    viewsets.ViewSet,
):
    scope_object = "query"
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]

    def get_usage(self, team, d: date, today: date) -> list:
        """Get SDK usage data for a specific day with caching"""
        cache_key = f"{SDK_USAGE_CACHE_KEY_PREFIX}{team.id}:{d.strftime('%Y-%m-%d')}"
        redis_client = redis.get_client()

        # Try to get from cache first
        cached = redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        # If not in cache, query ClickHouse
        date_str = d.strftime("%Y-%m-%d")

        libraries_or = ast.Or(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["properties", "$lib"]),
                    right=ast.Constant(value=lib["lib"]),
                )
                for lib in LIBRARIES
            ]
        )

        select = parse_select(
            """
            SELECT
                properties.$lib AS lib,
                properties.$lib_version AS lib_version,
                count(lib_version) as count
            FROM events
            WHERE toStartOfDay(timestamp) = toDate({date_str})
            AND ({libraries_or})
            GROUP BY lib, lib_version
            ORDER BY count DESC
        """,
            placeholders={"libraries_or": libraries_or, "date_str": ast.Constant(value=date_str)},
        )

        results = execute_hogql_query(query=select, team=team, query_type="SdkDeprecationWarnings")
        daily_data = results.results or []

        # Cache the results with appropriate TTL
        ttl = CURRENT_DAY_TTL if d == today else HISTORICAL_TTL
        redis_client.set(cache_key, json.dumps(daily_data), ex=ttl)

        return daily_data

    def _get_lib_data(self, lib_info: dict) -> dict:
        """Get combined data for a library (tags and deprecation)"""
        data = {}

        # Get tags data if URL exists
        if "tagsUrl" in lib_info:
            versions = get_tags(lib_info["lib"], lib_info["tagsUrl"])
            if versions:
                data["versions"] = versions

        # Get deprecation data if URL exists
        if "deprecationUrl" in lib_info:
            deprecation = get_deprecation(lib_info["lib"], lib_info["deprecationUrl"])
            if deprecation:
                data["deprecation"] = deprecation

        return data

    def _get_usage_data(self) -> SDKUsageData:
        """Get usage data for the last 7 days with caching"""
        today = datetime.now().date()
        days = [today - timedelta(days=i) for i in range(7)]
        date_range = [days[-1].strftime("%Y-%m-%d"), days[0].strftime("%Y-%m-%d")]
        # Define the date range

        # print days in YYYY-MM-DD format
        usage_data = SDKUsageData(libs={}, dateRange=date_range)

        for d in days:
            daily_data = self.get_usage(self.team, d, today)

            # Process the data
            date_str = d.strftime("%Y-%m-%d")
            for row in daily_data:
                lib, version, count = row[0], row[1], row[2]
                if lib not in usage_data.libs:
                    usage_data.libs[lib] = {}
                if version not in usage_data.libs[lib]:
                    usage_data.libs[lib][version] = {}
                usage_data.libs[lib][version][date_str] = count

        return usage_data

    def _check_for_warning(self, lib: str, version: str, versions_data: dict) -> Optional[SDKWarning]:
        warning: Optional[SDKWarning] = None

        # Check for explicit deprecation first
        if "deprecation" in versions_data and "deprecateBeforeVersion" in versions_data["deprecation"]:
            deprecate_before = versions_data["deprecation"]["deprecateBeforeVersion"]
            if diff_versions(deprecate_before, version):
                warning = SDKWarning(
                    latestAvailableVersion=None,  # TODO: pass in latest available
                    latestUsedVersion=version,
                    level=Level.WARNING,
                    message=f"Version {version} is deprecated. Please upgrade to at least version {deprecate_before}.",
                    lib=lib,
                )
                return warning

        # Check version difference if we have version data
        if versions_data.get("versions"):
            latest_version = versions_data["versions"][0]  # Assuming sorted from API
            sdk_versions = versions_data["versions"]

            diff = diff_versions(latest_version, version)
            if diff:
                num_versions_behind = next(
                    (i for i, v in enumerate(sdk_versions) if is_equal_version(v, version)), len(sdk_versions) - 1
                )

                if num_versions_behind < diff["diff"]:
                    num_versions_behind = diff["diff"]

                level = None

                if diff["kind"] == "major":
                    # if people have chosen to be on a different Major version, just provide an Info warning
                    level = Level.INFO
                elif num_versions_behind >= 50:
                    # if people are 50 versions behind, provide an Error warning
                    level = Level.ERROR
                elif num_versions_behind >= 40:
                    # shortly before giving people an Error warning, provide a Warning
                    level = Level.WARNING
                elif num_versions_behind >= 30:
                    # shortly before giving people a Warning, provide an Info warning
                    level = Level.INFO

                if level and version.strip():
                    warning = SDKWarning(
                        latestUsedVersion=version_to_string(version),
                        latestAvailableVersion=version_to_string(latest_version),
                        level=level,
                        numVersionsBehind=num_versions_behind,
                        lib=lib,
                    )

        return warning

    @action(methods=["GET"], detail=False)
    def warnings(self, request: request.Request, **kwargs) -> response.Response:
        usage_data = self._get_usage_data()

        warnings: list[SDKWarning] = []

        for lib in LIBRARIES:
            lib_name = lib["lib"]
            if lib_name in usage_data.libs:
                # Get the most recent version for this library
                most_recent_version = None
                most_recent_date = None

                for version, daily_counts in usage_data.libs[lib_name].items():
                    for date_str, _ in daily_counts.items():
                        if most_recent_date is None or date_str > most_recent_date:
                            most_recent_date = date_str
                            most_recent_version = version

                if most_recent_version:
                    versions_data = self._get_lib_data(lib)
                    if versions_data:
                        warning = self._check_for_warning(lib_name, most_recent_version, versions_data)
                        if warning:
                            warnings.append(warning)

        # Create a custom response with warnings and usage data
        response_data = SDKDeprecationWarningsResponse(warnings=warnings, usageData=usage_data)

        return response.Response(response_data.model_dump())
