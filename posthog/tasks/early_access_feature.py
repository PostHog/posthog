from celery import shared_task
import structlog
from posthog.cloud_utils import is_cloud
from posthog.models import EarlyAccessFeature
from posthog.models.person.person import Person
import posthoganalytics
from django.conf import settings

logger = structlog.get_logger(__name__)

POSTHOG_TEAM_ID = 2


# Note: If the task fails and is retried, events may be sent multiple times. This is handled by Customer.io when consuming the events.
@shared_task(ignore_result=True, max_retries=1)
def send_events_for_early_access_feature_stage_change(feature_id: str, from_stage: str, to_stage: str) -> None:
    print(
        f"[CELERY][EARLY ACCESS FEATURE] Sending events for early access feature stage change for feature {feature_id} from {from_stage} to {to_stage}"
    )  # noqa: T201
    instance = EarlyAccessFeature.objects.get(id=feature_id)

    team_id = instance.team.id

    send_events_for_change = (team_id is POSTHOG_TEAM_ID and is_cloud()) or settings.DEBUG

    if not send_events_for_change:
        print(  # noqa: T201
            f"[CELERY][EARLY ACCESS FEATURE] Skipping sending events for early access feature stage change for feature because it's not the PostHog team"
        )
        return

    feature_flag = instance.feature_flag

    logger.info(
        f"[CELERY][EARLY ACCESS FEATURE] Sending events for early access feature stage change for feature",
        feature_id=feature_id,
        from_stage=from_stage,
        to_stage=to_stage,
    )

    if not feature_flag:
        logger.warning(
            f"[CELERY][EARLY ACCESS FEATURE] Feature flag not found for feature",
            feature_id=feature_id,
        )
        return

    enrolled_persons = Person.objects.filter(
        **{f"properties__$feature_enrollment/{feature_flag.key}": True, "team_id": instance.team_id}
    )

    print(f"[CELERY][EARLY ACCESS FEATURE] Found {len(enrolled_persons)} persons enrolled in feature {feature_id}")  # noqa: T201

    for person in enrolled_persons:
        if len(person.distinct_ids) == 0:
            logger.warning(
                f"[CELERY][EARLY ACCESS FEATURE] Person has no distinct ids",
                person_id=person.id,
            )
            continue

        distinct_id = person.distinct_ids[0]
        email = person.properties.get("email", "")

        print(f"[CELERY][EARLY ACCESS FEATURE] Sending event for person {person.id} with distinct_id {distinct_id}")  # noqa: T201

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

        print(f"[CELERY][EARLY ACCESS FEATURE] Sent event for person {person.id} with distinct_id {distinct_id}")  # noqa: T201
