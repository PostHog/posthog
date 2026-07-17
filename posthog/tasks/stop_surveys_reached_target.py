from datetime import datetime
from itertools import groupby

from django.db.models import Q
from django.utils import timezone

from posthog.schema import ProductKey

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.models.activity_logging.activity_log import Change, Detail, Trigger, log_activity
from posthog.models.team.team import Team
from posthog.models.utils import UUIDT

from products.surveys.backend.models import Survey


def _get_surveys_response_counts(
    surveys_ids: list[UUIDT], team: Team, earliest_survey_creation_date: datetime
) -> dict[str, int]:
    tag_queries(product=ProductKey.SURVEYS, feature=Feature.QUERY)
    response = execute_hogql_query(
        """
        SELECT
            properties.$survey_id AS survey_id,
            count(DISTINCT if(
                coalesce(properties.$survey_submission_id, '') != '',
                properties.$survey_submission_id,
                toString(uuid)
            )) AS unique_responses
        FROM events
        WHERE event = 'survey sent'
            AND timestamp >= {earliest_survey_creation_date}
            AND properties.$survey_id IN {surveys_ids}
        GROUP BY survey_id
        LIMIT {limit}
        """,
        placeholders={
            "earliest_survey_creation_date": ast.Constant(value=earliest_survey_creation_date),
            "surveys_ids": ast.Constant(value=[str(survey_id) for survey_id in surveys_ids]),
            "limit": ast.Constant(value=len(surveys_ids)),
        },
        team=team,
        query_type="stop_surveys_reached_target",
        workload=Workload.OFFLINE,
    )

    return dict(response.results)


def _stop_survey_if_reached_limit(survey: Survey, responses_count: int) -> None:
    # Since the job might take a long time, the survey configuration could've been changed by the user
    # after we've queried it.
    survey.refresh_from_db()
    if survey.responses_limit is None or survey.end_date is not None:
        return

    if responses_count < survey.responses_limit:
        return

    reached_limit = survey.responses_limit
    survey.end_date = timezone.now()
    survey.responses_limit = None
    survey.save(update_fields=["end_date", "responses_limit"])
    _log_survey_closed_by_responses_limit(survey, reached_limit)


def _log_survey_closed_by_responses_limit(survey: Survey, reached_limit: int) -> None:
    # This task saves directly on the model, bypassing the API viewset that writes
    # activity-log entries. Without this, the survey stops with no trace and the user
    # has no way to see why. Mirror the schedule-close entry in update_survey_iteration.
    log_activity(
        organization_id=survey.team.organization_id,
        team_id=survey.team_id,
        user=None,  # system action: renders as PostHog in the activity log
        was_impersonated=False,
        item_id=survey.id,
        scope="Survey",
        activity="updated",
        detail=Detail(
            name=survey.name,
            changes=[Change(type="Survey", field="end_date", action="created", after=survey.end_date)],
            trigger=Trigger(
                job_type="stop_surveys_reached_target",
                job_id=str(survey.id),
                payload={"reason": "responses_limit_reached", "responses_limit": reached_limit},
            ),
        ),
    )


def stop_surveys_reached_target() -> None:
    all_surveys = Survey.objects.exclude(Q(responses_limit__isnull=True) | Q(end_date__isnull=False)).only(
        "id", "responses_limit", "team_id", "created_at"
    )

    all_surveys_sorted = sorted(all_surveys, key=lambda survey: survey.team_id)
    teams_by_id = Team.objects.in_bulk({survey.team_id for survey in all_surveys_sorted})
    for team_id, team_surveys in groupby(all_surveys_sorted, lambda survey: survey.team_id):
        team = teams_by_id.get(team_id)
        if team is None:
            continue

        team_surveys_list = list(team_surveys)
        surveys_ids = [survey.id for survey in team_surveys_list]
        earliest_survey_creation_date = min([survey.created_at for survey in team_surveys_list])

        response_counts = _get_surveys_response_counts(surveys_ids, team, earliest_survey_creation_date)
        for survey in team_surveys_list:
            survey_id = str(survey.id)
            if survey_id not in response_counts:
                continue

            _stop_survey_if_reached_limit(survey, response_counts[survey_id])
