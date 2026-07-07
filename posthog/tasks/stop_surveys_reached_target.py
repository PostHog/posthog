from itertools import groupby

from django.db.models import Q
from django.utils import timezone

from posthog.clickhouse.client.connection import Workload

from products.surveys.backend.models import Survey
from products.surveys.backend.responses import get_survey_response_counts


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
        "id", "responses_limit", "team_id", "created_at", "start_date", "end_date"
    )

    all_surveys_sorted = sorted(all_surveys, key=lambda survey: survey.team_id)
    for team_id, team_surveys in groupby(all_surveys_sorted, lambda survey: survey.team_id):
        team_surveys_list = list(team_surveys)

        response_counts = get_survey_response_counts(
            team_id=team_id,
            surveys=team_surveys_list,
            workload=Workload.OFFLINE,
        )
        for survey in team_surveys_list:
            survey_id = str(survey.id)
            if survey_id not in response_counts:
                continue

            _stop_survey_if_reached_limit(survey, response_counts[survey_id])
