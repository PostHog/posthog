from typing import cast
import posthoganalytics
from django.conf import settings
from posthog.cloud_utils import is_cloud
from posthog.models.user import User
from django.contrib.auth.models import AnonymousUser

REPLACE_FILTERS_FLAG = "hogql-insights-replace-filters"


def hogql_insights_enabled(user: User | AnonymousUser) -> bool:
    if settings.HOGQL_INSIGHTS_OVERRIDE is not None:
        return settings.HOGQL_INSIGHTS_OVERRIDE

    # on PostHog Cloud, use the feature flag
    if is_cloud():
        if not hasattr(user, "distinct_id"):  # exclude api endpoints that don't have auth from the flag
            return False

        return posthoganalytics.feature_enabled(
            "hogql-insights",
            cast(str, user.distinct_id),
            person_properties={"email": user.email},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    else:
        return False


def hogql_insights_replace_filters(team_id: int) -> bool:
    return posthoganalytics.feature_enabled(
        REPLACE_FILTERS_FLAG,
        f"team_{team_id}",
        group_properties={
            "project": {"id": team_id},
        },
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )
