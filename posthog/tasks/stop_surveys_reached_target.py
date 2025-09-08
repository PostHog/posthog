from datetime import datetime
from itertools import groupby

from django.db.models import Q
from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.models import Survey
from posthog.models.utils import UUIDT


def _get_surveys_response_counts(
    surveys_ids: list[UUIDT], team_id: int, earliest_survey_creation_date: datetime
) -> dict[str, int]:
    data = sync_execute(
        """
        SELECT JSONExtractString(properties, '$survey_id') as survey_id, count()
        FROM events
        WHERE event = 'survey sent'
              AND team_id = %(team_id)s
              AND timestamp >= %(earliest_survey_creation_date)s
              AND survey_id in %(surveys_ids)s
        GROUP BY survey_id
    """,
        {
            "surveys_ids": surveys_ids,
            "team_id": team_id,
            "earliest_survey_creation_date": earliest_survey_creation_date,
        },
        workload=Workload.OFFLINE,
    )

    counts = {}
    for survey_id, count in data:
        counts[survey_id] = count
    return counts


def _stop_survey_if_reached_limit(survey: Survey, responses_count: int) -> None:
    # Since the job might take a long time, the survey configuration could've been changed by the user
    # after we've queried it.
    survey.refresh_from_db()
    if survey.responses_limit is None or survey.end_date is not None:
        return

    if responses_count < survey.responses_limit:
        return

    survey.end_date = timezone.now()
    survey.responses_limit = None
    survey.save(update_fields=["end_date", "responses_limit"])


def stop_surveys_reached_target() -> None:
    all_surveys = Survey.objects.exclude(Q(responses_limit__isnull=True) | Q(end_date__isnull=False)).only(
        "id", "responses_limit", "team_id", "created_at"
    )

    all_surveys_sorted = sorted(all_surveys, key=lambda survey: survey.team_id)
    for team_id, team_surveys in groupby(all_surveys_sorted, lambda survey: survey.team_id):
        team_surveys_list = list(team_surveys)
        surveys_ids = [survey.id for survey in team_surveys_list]
        earliest_survey_creation_date = min([survey.created_at for survey in team_surveys_list])

        response_counts = _get_surveys_response_counts(surveys_ids, team_id, earliest_survey_creation_date)
        for survey in team_surveys_list:
            survey_id = str(survey.id)
            if survey_id not in response_counts:
                continue

            _stop_survey_if_reached_limit(survey, response_counts[survey_id])
