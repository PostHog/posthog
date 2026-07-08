import json
from datetime import datetime, timedelta

from django.utils.timezone import now

from posthog.clickhouse.client import sync_execute
from posthog.models.event.new_events_schema import events_read_table, use_new_events_schema

from products.surveys.backend.models import Survey
from products.surveys.backend.util import SurveyEventProperties, get_survey_property_string_expr


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

    total_response_count = _get_survey_responses_count(survey.id, survey.team_id)
    if total_response_count < today_entry.get("daily_response_limit", 0) and survey.internal_response_sampling_flag:
        # Update the internal_response_sampling_flag's rollout percentage
        internal_response_sampling_flag = survey.internal_response_sampling_flag
        # groups[0] is guaranteed to exist — survey flags are always created with groups in filters
        # (see SurveySerializer._add_internal_response_sampling_filters)
        internal_response_sampling_flag.filters["groups"][0]["rollout_percentage"] = today_entry["rollout_percentage"]
        internal_response_sampling_flag.save(update_fields=["filters"])

    # this also doubles as a way to check that we're processing the final entry in the current sequence.
    if today_entry["rollout_percentage"] == 100:
        tomorrow = today_date + timedelta(days=1)
        survey.response_sampling_start_date = tomorrow
        survey.save(update_fields=["response_sampling_start_date", "response_sampling_daily_limits"])


def _get_survey_responses_count(survey_id: int, team_id: int) -> int:
    use_new = use_new_events_schema(team_id)
    survey_id_expr = get_survey_property_string_expr(SurveyEventProperties.SURVEY_ID, use_new_events_schema=use_new)

    # nosemgrep: clickhouse-fstring-param-audit - survey property/table expressions come from internal helpers
    data = sync_execute(
        f"""
                SELECT {survey_id_expr} as survey_id, count()
                FROM {events_read_table(use_new)}
                WHERE event = 'survey sent' AND {survey_id_expr} = %(survey_id)s
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
    ).only("id", "team_id", "response_sampling_daily_limits")

    for survey in list(surveys_with_adaptive_sampling):
        _update_survey_adaptive_sampling(survey)
