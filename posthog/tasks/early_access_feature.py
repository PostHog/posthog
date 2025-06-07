from celery import shared_task
import structlog
from posthog.cloud_utils import is_cloud
from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.models import EarlyAccessFeature
import posthoganalytics


logger = structlog.get_logger(__name__)

POSTHOG_TEAM_ID = 2


# Note: If the task fails and is retried, events may be sent multiple times. This is handled by Customer.io when consuming the events.
@shared_task(ignore_result=True, max_retries=1)
def send_events_for_early_access_feature_stage_change(feature_id: str, from_stage: str, to_stage: str) -> None:
    print(  # noqa: T201
        f"[CELERY][EARLY ACCESS FEATURE] Sending events for early access feature stage change for feature {feature_id} from {from_stage} to {to_stage}"
    )
    instance = EarlyAccessFeature.objects.get(id=feature_id)

    team_id = instance.team.id

    send_events_for_change = team_id == POSTHOG_TEAM_ID if is_cloud() else True

    if not send_events_for_change:
        print(  # noqa: T201
            f"[CELERY][EARLY ACCESS FEATURE] Skipping sending events for early access feature stage change for feature because it's not the PostHog team"
        )
        return

    feature_flag = instance.feature_flag

    print(  # noqa: T201
        f"[CELERY][EARLY ACCESS FEATURE] Sending events for early access feature stage change for feature {feature_id} from {from_stage} to {to_stage}"
    )

    if not feature_flag:
        print(  # noqa: T201
            f"[CELERY][EARLY ACCESS FEATURE] Feature flag not found for feature {feature_id}"
        )
        return

    print(f"[CELERY][EARLY ACCESS FEATURE] Feature flag: {feature_flag.key}")  # noqa: T201
    print(f"[CELERY][EARLY ACCESS FEATURE] Team: {instance.team.id}")  # noqa: T201

    # Get the unique persons enrolled in the feature along with their distinct ID
    response = execute_hogql_query(
        """
        SELECT
            argMax(id, created_at) AS id,
            JSONExtractString(properties, 'email') AS email,
            argMax(pdi.distinct_id, created_at) as distinct_id
        FROM persons
        WHERE JSONExtractString(properties, {enrollment_key}) = 'true'
        AND team_id = {team_id}
        AND notEmpty(JSONExtractString(properties, 'email'))
        GROUP BY JSONExtractString(properties, 'email')
        """,
        placeholders={
            "enrollment_key": ast.Constant(value=f"$feature_enrollment/{feature_flag.key}"),
            "team_id": ast.Constant(value=instance.team.id),
        },
        team=instance.team,
    )

    print(f"[CELERY][EARLY ACCESS FEATURE] Query: {response.query}")  # noqa: T201

    enrolled_persons = response.results

    print(f"[CELERY][EARLY ACCESS FEATURE] Found {len(enrolled_persons)} persons enrolled in feature {feature_id}")  # noqa: T201

    for id, email, distinct_id in enrolled_persons:
        print(f"[CELERY][EARLY ACCESS FEATURE] Sending event for person {id} with distinct_id {distinct_id}")  # noqa: T201

        posthoganalytics.capture(
            distinct_id,
            "user moved feature preview stage",
            {
                "from": from_stage,
                "to": to_stage,
                "feature_flag_key": feature_flag.key,
                "feature_id": instance.id,
                "feature_name": instance.name,
                "user_email": email,
            },
        )

        print(f"[CELERY][EARLY ACCESS FEATURE] Sent event for person {id} with distinct_id {distinct_id}")  # noqa: T201
