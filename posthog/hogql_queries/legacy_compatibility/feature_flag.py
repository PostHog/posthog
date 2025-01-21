import posthoganalytics
from posthog.models import Team


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
