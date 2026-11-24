from django.db.models import Q

from posthog.constants import ENRICHED_DASHBOARD_INSIGHT_IDENTIFIER

FEATURE_FLAG_TOTAL_VOLUME_INSIGHT_NAME = "Feature Flag Called Total Volume"
# The unique-calls name embeds the pluralized aggregation entity, so only its ends are fixed.
FEATURE_FLAG_UNIQUE_CALLS_INSIGHT_NAME_PREFIX = "Feature Flag calls made by unique "
FEATURE_FLAG_UNIQUE_CALLS_INSIGHT_NAME_SUFFIX = " per variant"
FEATURE_FLAG_UNIQUE_USERS_INSIGHT_NAME = (
    f"{FEATURE_FLAG_UNIQUE_CALLS_INSIGHT_NAME_PREFIX}users{FEATURE_FLAG_UNIQUE_CALLS_INSIGHT_NAME_SUFFIX}"
)
# The generated descriptions interpolate the flag key, so only their ends are fixed.
FEATURE_FLAG_CALLS_DESCRIPTION_PREFIX = "Shows the number of"
FEATURE_FLAG_CALLS_DESCRIPTION_FRAGMENT = "calls made on feature flag"
FEATURE_FLAG_ENRICHED_VIEW_INSIGHT_NAME = f"{ENRICHED_DASHBOARD_INSIGHT_IDENTIFIER} Total Volume"
FEATURE_FLAG_ENRICHED_INTERACTION_INSIGHT_NAME = "Feature Interaction Total Volume"
FEATURE_FLAG_ENRICHED_INSIGHT_DESCRIPTION = (
    "Shows the total number of times this feature was viewed and interacted with"
)


def feature_flag_generated_insight_q() -> Q:
    """Match the generated insights on a feature flag usage dashboard.

    A name on its own is not provenance, because a person can type any of these. This query
    therefore pairs each name with the description that PostHog generated beside it. That makes
    this narrower than `delete_feature_flag_usage_insights._classifier_q`, which matches a name or a
    description so a cleanup sweep still reaches rows an older template version wrote.
    """
    return Q(
        Q(name=FEATURE_FLAG_TOTAL_VOLUME_INSIGHT_NAME)
        | Q(
            name__startswith=FEATURE_FLAG_UNIQUE_CALLS_INSIGHT_NAME_PREFIX,
            name__endswith=FEATURE_FLAG_UNIQUE_CALLS_INSIGHT_NAME_SUFFIX,
        ),
        description__startswith=FEATURE_FLAG_CALLS_DESCRIPTION_PREFIX,
        description__contains=FEATURE_FLAG_CALLS_DESCRIPTION_FRAGMENT,
    ) | Q(
        name__in=[FEATURE_FLAG_ENRICHED_VIEW_INSIGHT_NAME, FEATURE_FLAG_ENRICHED_INTERACTION_INSIGHT_NAME],
        description=FEATURE_FLAG_ENRICHED_INSIGHT_DESCRIPTION,
    )
