import json

from rest_framework import request, response, viewsets

from posthog import redis
from posthog.api.utils import action
from typing import Optional, Union
import requests

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

CACHE_KEY_PREFIX = "@posthog/sdk-versions/"
CACHE_TTL = 5 * 60  # 5 minutes in seconds


def get_cached_versions(lib_info: dict) -> Optional[dict]:
    redis_client = redis.get_client()
    lib = lib_info["lib"]

    # Try to get from cache first
    cached = redis_client.get(f"{CACHE_KEY_PREFIX}{lib}")
    if cached:
        return json.loads(cached)

    data = {}

    # Fetch tags if URL exists
    if "tagsUrl" in lib_info:
        try:
            response = requests.get(lib_info["tagsUrl"])
            if response.status_code == 200:
                data["versions"] = [tag["name"].lstrip("v") for tag in response.json()]
        except Exception:
            pass

    # Fetch deprecation info if URL exists
    if "deprecationUrl" in lib_info:
        try:
            response = requests.get(lib_info["deprecationUrl"])
            if response.status_code == 200:
                data["deprecation"] = response.json()
        except Exception:
            pass

    if data:
        redis_client.set(f"{CACHE_KEY_PREFIX}{lib}", json.dumps(data), ex=CACHE_TTL)
        return data

    return None

class SdkDeprecationWarningsViewSet(
    TeamAndOrgViewSetMixin,
    viewsets.ViewSet,
):
    scope_object = "query"
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]

    def check_for_warning(self, lib: str, version: str, versions_data: dict) -> Optional[dict]:
        warning: Optional[dict[str, Union[str, int]]] = None

        # Check for explicit deprecation first
        if "deprecation" in versions_data and "deprecateBeforeVersion" in versions_data["deprecation"]:
            deprecate_before = versions_data["deprecation"]["deprecateBeforeVersion"]
            if diff_versions(deprecate_before, version):
                warning = {
                    "latestUsedVersion": version,
                    "level": "error",
                    "message": f"Version {version} is deprecated. Please upgrade to at least version {deprecate_before}."
                }
                return warning

        # Check version difference if we have version data
        if versions_data.get("versions"):
            latest_version = versions_data["versions"][0]  # Assuming sorted from API
            sdk_versions = versions_data["versions"]

            diff = diff_versions(latest_version, version)
            if diff:
                num_versions_behind = next(
                    (i for i, v in enumerate(sdk_versions) if is_equal_version(v, version)),
                    len(sdk_versions) - 1
                )

                if num_versions_behind < diff["diff"]:
                    num_versions_behind = diff["diff"]

                level = None
                if diff["kind"] == "major":
                    level = "info"
                elif diff["kind"] == "minor" and num_versions_behind >= 40:
                    level = "warning"

                if level is None and num_versions_behind >= 50:
                    level = "error"

                if level and version.strip():
                    warning = {
                        "latestUsedVersion": version_to_string(version),
                        "latestAvailableVersion": version_to_string(latest_version),
                        "level": level,
                        "numVersionsBehind": num_versions_behind,
                    }

        return warning

    @action(methods=["GET"], detail=False)
    def warnings(self, request: request.Request, **kwargs) -> response.Response:
        libraries_or = ast.Or(exprs=[ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["properties","$lib"]), right=ast.Constant(value=lib["lib"])) for lib in LIBRARIES])

        select = parse_select('''
            SELECT
                properties.$lib AS lib,
                properties.$lib_version AS lib_version,
                max(timestamp) AS latest_timestamp,
                count(lib_version) as count
            FROM events
            WHERE timestamp >= now() - INTERVAL 1 DAY
            AND timestamp <= now()
            AND ({libraries_or})
            GROUP BY lib, lib_version
            ORDER BY latest_timestamp DESC
            limit 100
        ''', placeholders={
            "libraries_or": libraries_or
        })

        results = execute_hogql_query(query=select, team=self.team, query_type='SdkDeprecationWarnings')

        # Group results by lib to find latest version for each
        lib_versions: dict[str, str] = {}
        for row in results.results or []:
            lib, version = row[0], row[1]
            if lib not in lib_versions or not lib_versions[lib]:
                lib_versions[lib] = version

        warnings = []
        for lib in LIBRARIES:
            lib_name = lib["lib"]
            if lib_name in lib_versions:
                versions_data = get_cached_versions(lib)
                if versions_data:
                    warning = self.check_for_warning(lib_name, lib_versions[lib_name], versions_data)
                    if warning:
                        warning["lib"] = lib_name
                        warnings.append(warning)

        return response.Response(warnings)




