import posthoganalytics
from django.conf import settings
from posthog.models.user import User

from posthog.schema import InsightType


GLOBAL_FLAG = "hogql-insights-preview"
INSIGHT_TYPE_TO_FLAG: dict[InsightType, str] = {
    InsightType.TRENDS: "hogql-insights-trends",
    InsightType.FUNNELS: "hogql-insights-funnels",
    InsightType.RETENTION: "hogql-insights-retention",
    InsightType.PATHS: "hogql-insights-paths",
    InsightType.LIFECYCLE: "hogql-insights-lifecycle",
    InsightType.STICKINESS: "hogql-insights-stickiness",
}


def hogql_insights_enabled(user: User, insight_type: InsightType) -> bool:
    if settings.HOGQL_INSIGHTS_OVERRIDE is not None:
        return settings.HOGQL_INSIGHTS_OVERRIDE

    if posthoganalytics.feature_enabled(
        GLOBAL_FLAG,
        user.distinct_id,
        person_properties={"email": user.email},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    ):
        # HogQL insights enabled all the way
        return True

    return posthoganalytics.feature_enabled(
        INSIGHT_TYPE_TO_FLAG[insight_type],
        user.distinct_id,
        person_properties={"email": user.email},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )
