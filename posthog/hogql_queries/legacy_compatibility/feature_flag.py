from typing import Literal, Optional, TYPE_CHECKING
import posthoganalytics
from posthog.models import Team
from rest_framework.request import Request

if TYPE_CHECKING:
    from posthog.models import User


def hogql_insights_replace_filters(team: Team) -> bool:
    return posthoganalytics.feature_enabled(
        "hogql-insights-replace-filters",
        str(team.uuid),
        groups={
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        group_properties={
            "organization": {
                "id": str(team.organization_id),
            },
            "project": {
                "id": str(team.id),
            },
        },
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


def insight_funnels_use_udf(team: Team) -> bool:
    return posthoganalytics.feature_enabled(
        "insight-funnels-use-udf",
        str(team.uuid),
        groups={
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        group_properties={
            "organization": {
                "id": str(team.organization_id),
            },
            "project": {
                "id": str(team.id),
            },
        },
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )


def insight_funnels_use_udf_time_to_convert(team: Team) -> bool:
    return posthoganalytics.feature_enabled(
        "insight-funnels-use-udf-time-to-convert",
        str(team.uuid),
        groups={
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        group_properties={
            "organization": {
                "id": str(team.organization_id),
            },
            "project": {
                "id": str(team.id),
            },
        },
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )


def insight_funnels_use_udf_trends(team: Team) -> bool:
    return posthoganalytics.feature_enabled(
        "insight-funnels-use-udf-trends",
        str(team.uuid),
        groups={
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        group_properties={
            "organization": {
                "id": str(team.organization_id),
            },
            "project": {
                "id": str(team.id),
            },
        },
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )


def insight_api_use_legacy_queries(team: Team) -> bool:
    """
    Use the legacy implementation of insight api calculation endpoints.
    """
    return posthoganalytics.feature_enabled(
        "insight-api-use-legacy-queries",
        str(team.uuid),
        groups={
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        group_properties={
            "organization": {
                "id": str(team.organization_id),
            },
            "project": {
                "id": str(team.id),
            },
        },
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


def query_cache_use_s3(team: Team, user: Optional["User"] = None) -> bool:
    """
    Use S3 instead of Redis for query caching.

    Args:
        team: The team to check the feature flag for
        user: Optional user to check user-specific feature flags
    """
    # Use user-specific evaluation if user is provided
    distinct_id = str(user.distinct_id) if user else str(team.uuid)

    return posthoganalytics.feature_enabled(
        "query-cache-use-s3",
        distinct_id,
        groups={
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        group_properties={
            "organization": {
                "id": str(team.organization_id),
            },
            "project": {
                "id": str(team.id),
            },
        },
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


LegacyAPIQueryMethod = Literal["legacy", "hogql"]


def get_query_method(request: Request, team: Team) -> LegacyAPIQueryMethod:
    query_method_param = request.query_params.get("query_method", None)
    if query_method_param in ["hogql", "legacy"]:
        return query_method_param  # type: ignore
    return "legacy" if insight_api_use_legacy_queries(team) else "hogql"
