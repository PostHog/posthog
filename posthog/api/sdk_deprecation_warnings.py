
from rest_framework import request, response, viewsets
from posthog.api.utils import action

from posthog.api.routing import TeamAndOrgViewSetMixin
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


class SdkDeprecationWarningsViewSet(
    TeamAndOrgViewSetMixin,
    viewsets.ViewSet,
):
    scope_object = "query"
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]

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

        results = execute_hogql_query(query = select, team=self.team, query_type='SdkDeprecationWarnings')

        print(results)

        return response.Response(results)




