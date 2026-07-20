import json
from datetime import datetime, timedelta

from django.utils.timezone import now

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from products.surveys.backend.models import Survey


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

    total_response_count = _get_survey_responses_count(survey)
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


def _get_survey_responses_count(survey: Survey) -> int:
    response = execute_hogql_query(
        """
        SELECT count()
        FROM events
        WHERE event = 'survey sent'
            AND properties.$survey_id = {survey_id}
        """,
        placeholders={"survey_id": ast.Constant(value=str(survey.id))},
        team=survey.team,
        query_type="update_survey_adaptive_sampling",
    )
    return response.results[0][0] if response.results else 0


def update_survey_adaptive_sampling() -> None:
    surveys_with_adaptive_sampling = Survey.objects.filter(
        start_date__isnull=False, end_date__isnull=True, response_sampling_daily_limits__isnull=False
    ).only("id", "team_id", "response_sampling_daily_limits")

    for survey in list(surveys_with_adaptive_sampling):
        _update_survey_adaptive_sampling(survey)
