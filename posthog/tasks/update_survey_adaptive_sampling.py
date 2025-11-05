import json
from datetime import datetime, timedelta

from django.utils.timezone import now

from posthog.clickhouse.client import sync_execute
from posthog.models import Survey


def _update_survey_adaptive_sampling(survey: Survey) -> None:
    survey.refresh_from_db()
    if survey.response_sampling_daily_limits is None or survey.end_date is not None:
        return
    # Get today's date in UTC
    today_date = now().date()
    today_entry = None
    response_sampling_daily_limits = json.loads(survey.response_sampling_daily_limits)

    for entry in response_sampling_daily_limits:
        if datetime.fromisoformat(entry.get("date")).date() == today_date:
            today_entry = entry

    if today_entry is None:
        return

    total_response_count = _get_survey_responses_count(survey.id)
    if total_response_count < today_entry.get("daily_response_limit", 0) and survey.internal_response_sampling_flag:
        # Update the internal_response_sampling_flag's rollout percentage
        internal_response_sampling_flag = survey.internal_response_sampling_flag
        internal_response_sampling_flag.rollout_percentage = today_entry["rollout_percentage"]
        internal_response_sampling_flag.save()

    # this also doubles as a way to check that we're processing the final entry in the current sequence.
    if today_entry["rollout_percentage"] == 100:
        tomorrow = today_date + timedelta(days=1)
        survey.response_sampling_start_date = tomorrow
        survey.save(update_fields=["response_sampling_start_date", "response_sampling_daily_limits"])


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
        start_date__isnull=False, end_date__isnull=True, response_sampling_daily_limits__isnull=False
    ).only("id", "response_sampling_daily_limits")

    for survey in list(surveys_with_adaptive_sampling):
        _update_survey_adaptive_sampling(survey)
