from typing import Any, Optional

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

import structlog
import posthoganalytics
from celery import shared_task

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.cloud_utils import is_cloud
from posthog.models import Team
from posthog.scoping_audit import skip_team_scope_audit

from products.early_access_features.backend.models import EarlyAccessFeature
from products.surveys.backend.models import Survey

logger = structlog.get_logger(__name__)

POSTHOG_TEAM_ID = 2

# Gate for auto-creating a waitlist survey per "Coming Soon" (concept-stage) feature, and
# for showing the email field in-app. Enable for PostHog's own project first.
COMING_SOON_WAITLIST_SURVEYS_FLAG = "coming-soon-waitlist-surveys"


def coming_soon_waitlist_surveys_enabled(team: Team) -> bool:
    """Whether the auto-survey behavior is enabled for this team (evaluated by project group)."""
    return bool(
        posthoganalytics.feature_enabled(
            COMING_SOON_WAITLIST_SURVEYS_FLAG,
            str(team.id),
            groups={"project": str(team.id)},
            group_properties={"project": {"id": str(team.id)}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )


def ensure_waitlist_survey_for_feature(instance: EarlyAccessFeature) -> Optional[Survey]:
    """
    Idempotently ensure a concept-stage Early Access Feature has a linked `api` waitlist
    survey, and record its id (+ first question id) on the feature's payload so posthog-js
    consumers (posthog.com/roadmap and the in-app Feature Previews) know where to send the
    email. Returns the survey, or None if not applicable (wrong stage, survey already
    linked, or no flag — callers only need "nothing to do", so the reasons are deliberately
    not distinguished). Does NOT check the gating flag — callers decide that.
    """
    if instance.stage != EarlyAccessFeature.Stage.CONCEPT:
        return None
    if instance.payload and instance.payload.get("survey_id"):
        return None
    feature_flag = instance.feature_flag
    if not feature_flag:
        return None

    # Reuse an existing api survey linked to this flag if one exists (handles re-runs and
    # the (team, name) uniqueness constraint).
    survey = Survey.objects.filter(team=instance.team, linked_flag=feature_flag, type=Survey.SurveyType.API).first()
    if survey is None:
        # Serialize concurrent creates for the same flag (the signal firing on create and
        # again on an immediate edit, or the backfill colliding with the signal) with a
        # transaction-scoped advisory lock. Without it, a task committing between another
        # task's linked-survey check and its name-collision check pushes the second task
        # onto the "(flag-key)" suffixed name, leaving two api surveys linked to one flag.
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [instance.team_id, feature_flag.id])
            # Re-check under the lock: the winner may have committed after the check above.
            survey = Survey.objects.filter(
                team=instance.team, linked_flag=feature_flag, type=Survey.SurveyType.API
            ).first()
            if survey is None:
                name = f"{instance.name} waitlist"[:380]
                if Survey.objects.filter(team=instance.team, name=name).exists():
                    name = f"{name} ({feature_flag.key})"[:400]
                try:
                    # The lock only serializes same-flag creates, so (team, name) can still
                    # collide with a survey created concurrently for a different flag. The
                    # savepoint keeps the transaction usable so we can adopt or re-raise.
                    with transaction.atomic():
                        survey = Survey.objects.create(
                            team=instance.team,
                            name=name,
                            description=f"Waitlist sign-ups for the upcoming {instance.name} feature.",
                            type=Survey.SurveyType.API,
                            linked_flag=feature_flag,
                            questions=[
                                {
                                    "type": "open",
                                    "question": f"Enter your email and we'll let you know when {instance.name} is ready.",
                                    "optional": False,
                                }
                            ],
                            start_date=timezone.now(),
                        )
                except IntegrityError:
                    survey = Survey.objects.filter(
                        team=instance.team, linked_flag=feature_flag, type=Survey.SurveyType.API
                    ).first()
                    if survey is None:
                        raise

    # `ensure_question_ids` (pre_save) guarantees the question has an id.
    question_id = (survey.questions or [{}])[0].get("id")
    # The merge below is over the payload snapshot read when `instance` was loaded — a
    # concurrent write to a different payload key between that read and this update gets
    # dropped. Fine while this task is the only payload writer besides the API.
    EarlyAccessFeature.objects.filter(pk=instance.pk).update(
        payload={**(instance.payload or {}), "survey_id": str(survey.id), "survey_question_id": question_id}
    )
    return survey


@shared_task(ignore_result=True, max_retries=3, autoretry_for=(Exception,), retry_backoff=True)
@skip_team_scope_audit
def create_waitlist_survey_for_concept_feature(feature_id: str) -> None:
    try:
        instance = EarlyAccessFeature.objects.select_related("feature_flag", "team").get(id=feature_id)
    except EarlyAccessFeature.DoesNotExist:
        return
    if not coming_soon_waitlist_surveys_enabled(instance.team):
        return
    ensure_waitlist_survey_for_feature(instance)


# Mostly here to help with mocks for testing
def capture_event(event: str, *, distinct_id: str, properties: dict[str, Any]) -> None:
    posthoganalytics.capture(
        event,
        distinct_id=distinct_id,
        properties=properties,
    )


# Note: If the task fails and is retried, events may be sent multiple times. This is handled by Customer.io when consuming the events.
@shared_task(ignore_result=True, max_retries=3)
@skip_team_scope_audit
def send_events_for_early_access_feature_stage_change(feature_id: str, from_stage: str, to_stage: str) -> None:
    instance = EarlyAccessFeature.objects.get(id=feature_id)

    team_id = instance.team.id
    send_events_for_change = team_id == POSTHOG_TEAM_ID if is_cloud() else True
    if not send_events_for_change:
        return

    feature_flag = instance.feature_flag
    if not feature_flag:
        return

    # Get the unique persons enrolled in the feature along with their distinct ID.
    # Property access (rather than JSONExtractString) lets the HogQL printer use
    # materialized person-property columns when available.
    response = execute_hogql_query(
        """
        SELECT
            argMax(id, created_at) AS id,
            properties.email AS email,
            argMax(pdi.distinct_id, created_at) as distinct_id
        FROM persons
        WHERE properties[{enrollment_key}] = 'true'
        AND notEmpty(properties.email)
        GROUP BY properties.email
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
