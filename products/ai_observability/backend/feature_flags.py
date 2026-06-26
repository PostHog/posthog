from __future__ import annotations

import posthoganalytics

from posthog.models import Team, User

SENTIMENT_EVALUATIONS_FEATURE_FLAG = "llm-analytics-sentiment-evaluations"


def is_sentiment_evaluations_enabled(user: User, team: Team) -> bool:
    distinct_id = user.distinct_id or str(user.uuid)
    organization_id = str(team.organization_id)
    project_id = str(team.id)

    return posthoganalytics.feature_enabled(
        SENTIMENT_EVALUATIONS_FEATURE_FLAG,
        distinct_id,
        groups={"organization": organization_id, "project": project_id},
        group_properties={"organization": {"id": organization_id}, "project": {"id": project_id}},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )
