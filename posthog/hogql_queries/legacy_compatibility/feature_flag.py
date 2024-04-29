import posthoganalytics
from django.conf import settings
from posthog.models import User, Team


def should_use_hogql_backend_in_insight_serialization(user: User) -> bool:
    if settings.HOGQL_INSIGHTS_OVERRIDE is not None:
        return settings.HOGQL_INSIGHTS_OVERRIDE

    return posthoganalytics.feature_enabled(
        "hogql-in-insight-serialization",
        user.distinct_id,
        person_properties={"email": user.email},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


def hogql_insights_replace_filters(team: Team) -> bool:
    return posthoganalytics.feature_enabled(
        "hogql-insights-replace-filters",
        str(team.uuid),
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )
