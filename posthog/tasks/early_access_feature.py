from typing import Any

import structlog
import posthoganalytics
from celery import shared_task

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.cloud_utils import is_cloud

from products.early_access_features.backend.models import EarlyAccessFeature

logger = structlog.get_logger(__name__)

POSTHOG_TEAM_ID = 2


# Mostly here to help with mocks for testing
def capture_event(event: str, *, distinct_id: str, properties: dict[str, Any]) -> None:
    posthoganalytics.capture(
        event,
        distinct_id=distinct_id,
        properties=properties,
    )


# Note: If the task fails and is retried, events may be sent multiple times. This is handled by Customer.io when consuming the events.
@shared_task(ignore_result=True, max_retries=3)
def send_events_for_early_access_feature_stage_change(feature_id: str, from_stage: str, to_stage: str) -> None:
    instance = EarlyAccessFeature.objects.get(id=feature_id)

    team_id = instance.team.id
    send_events_for_change = team_id == POSTHOG_TEAM_ID if is_cloud() else True
    if not send_events_for_change:
        return

    feature_flag = instance.feature_flag
    if not feature_flag:
        return

    # Get the unique persons enrolled in the feature along with their distinct ID
    response = execute_hogql_query(
        """
        SELECT
            argMax(id, created_at) AS id,
            JSONExtractString(properties, 'email') AS email,
            argMax(pdi.distinct_id, created_at) as distinct_id
        FROM persons
        WHERE JSONExtractString(properties, {enrollment_key}) = 'true'
        AND notEmpty(JSONExtractString(properties, 'email'))
        GROUP BY JSONExtractString(properties, 'email')
        LIMIT {limit}
        """,
        placeholders={
            "enrollment_key": ast.Constant(value=f"$feature_enrollment/{feature_flag.key}"),
            "limit": ast.Constant(value=MAX_SELECT_RETURNED_ROWS),
        },
        team=instance.team,
        limit_context=LimitContext.QUERY_ASYNC,
    )

    enrolled_persons = response.results
    for _id, email, distinct_id in enrolled_persons:
        capture_event(
            "user moved feature preview stage",
            distinct_id=distinct_id,
            properties={
                "from": from_stage,
                "to": to_stage,
                "feature_flag_key": feature_flag.key,
                "feature_id": instance.id,
                "feature_name": instance.name,
                "user_email": email,
            },
        )

    posthoganalytics.flush()
