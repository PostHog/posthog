import posthoganalytics
from django.conf import settings
from posthog.cloud_utils import is_cloud
from posthog.models.user import User


def hogql_insights_enabled(user: User) -> bool:
    if settings.HOGQL_INSIGHTS_OVERRIDE is not None:
        return settings.HOGQL_INSIGHTS_OVERRIDE

    # on PostHog Cloud, use the feature flag
    if is_cloud():
        return posthoganalytics.feature_enabled(
            "hogql-insights",
            user.distinct_id,
            person_properties={"email": user.email},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    else:
        return False
