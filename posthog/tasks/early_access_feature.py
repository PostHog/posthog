from celery import shared_task
import structlog
from posthog.models import EarlyAccessFeature
from posthog.models.person.person import Person
import posthoganalytics

logger = structlog.get_logger(__name__)


# Note: If the task fails and is retried, events may be sent multiple times. This is handled by Customer.io when consuming the events.
@shared_task(ignore_result=True, max_retries=1)
def send_events_for_early_access_feature_stage_change(feature_id: str, from_stage: str, to_stage: str) -> None:
    instance = EarlyAccessFeature.objects.get(id=feature_id)

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

    logger.info(
        f"[CELERY][EARLY ACCESS FEATURE] Found {len(enrolled_persons)} persons enrolled in feature",
        feature_id=feature_id,
    )

    for person in enrolled_persons:
        if len(person.distinct_ids) == 0:
            logger.warning(
                f"[CELERY][EARLY ACCESS FEATURE] Person has no distinct ids",
                person_id=person.id,
            )
            continue

        distinct_id = person.distinct_ids[0]
        email = person.properties.get("email", "")

        logger.info(
            f"[CELERY][EARLY ACCESS FEATURE] Sending event for person",
            person_id=person.id,
            distinct_id=distinct_id,
            email=email,
        )

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

        logger.info(
            f"[CELERY][EARLY ACCESS FEATURE] Sent event for person",
            person_id=person.id,
            distinct_id=distinct_id,
            email=email,
        )
