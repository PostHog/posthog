from datetime import datetime
from django.utils.timezone import now

from posthog.clickhouse.client import sync_execute
from posthog.models import Survey


def _update_survey_adaptive_sampling(survey: Survey) -> None:
    survey.refresh_from_db()
    if survey.response_sampling_daily_limits is None or survey.end_date is not None:
        return
    # Get today's date in UTC
    today_date = now().date()

    # Find today's rollout percentage from the schedule
    today_entry = next(
        (entry for entry in survey.rollout_schedule if datetime.fromisoformat(entry["date"]).date() == today_date), None
    )

    total_response_count = _get_survey_responses_count(survey.id)
    if total_response_count < today_entry["daily_response_limit"]:
        # Update the targeting_feature_flag's rollout percentage
        targeting_flag = survey.targeting_flag
        targeting_flag.rollout_percentage = today_entry["rollout_percentage"]
        targeting_flag.save()


def _get_survey_responses_count(survey_id: int) -> int:
    data = sync_execute(
        f"""
                SELECT JSONExtractString(properties, '$survey_id') as survey_id, count()
                FROM events
                WHERE event = 'survey sent' AND survey_id = %(survey_id)s
            """,
        {"survey_id": survey_id},
    )

    counts = {}
    for survey_id, count in data:
        counts[survey_id] = count

    return counts[survey_id]


def update_survey_adaptive_sampling() -> None:
    surveys_with_adaptive_sampling = Survey.objects.filter(
        start_date__isnull=False, end_date__isnull=True, response_sampling_daily_limits__is_null=False
    ).only("id", "iteration_count", "response_sampling_daily_limits")

    for survey in list(surveys_with_adaptive_sampling):
        _update_survey_adaptive_sampling(survey)
