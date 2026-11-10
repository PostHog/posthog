from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from posthog.api.person import get_person_name
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.person.util import get_persons_mapped_by_distinct_id
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.widget_specs.configs import SURVEY_RESULTS_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.dashboards.backend.widgets.dashboard_filters import (
    NO_DASHBOARD_FILTERS,
    WidgetDashboardFilters,
    parse_widget_datetime,
)
from products.surveys.backend.models import Survey
from products.surveys.backend.responses import SurveyResponseRow, fetch_response_rows, get_survey_stats

logger = logging.getLogger(__name__)


def _serialize_survey_summary(survey: Survey) -> dict[str, Any]:
    return {
        "id": str(survey.id),
        "name": survey.name,
        "type": survey.type,
        "archived": survey.archived,
        "start_date": survey.start_date.isoformat() if survey.start_date else None,
        "end_date": survey.end_date.isoformat() if survey.end_date else None,
    }


def _serialize_response_row(row: SurveyResponseRow, person_display_name: str | None) -> dict[str, Any]:
    return {
        "uuid": row.uuid,
        "distinct_id": row.distinct_id,
        "person_display_name": person_display_name,
        "session_id": row.session_id,
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
        "answers": [
            {
                "question_id": answer.question_id,
                "question_text": answer.question_text,
                "question_type": answer.question_type,
                "answer": answer.answer,
            }
            for answer in row.answers
        ],
    }


def _resolve_person_display_names(team: Team, rows: list[SurveyResponseRow]) -> dict[str, str]:
    """Map each row's distinct_id to a human-friendly person display name (email/name).

    Best-effort: distinct_ids without a matched person are simply omitted, and the
    frontend falls back to the distinct_id itself.
    """
    distinct_ids = list({row.distinct_id for row in rows if row.distinct_id})
    if not distinct_ids:
        return {}
    persons_by_distinct_id = get_persons_mapped_by_distinct_id(team.pk, distinct_ids)
    return {distinct_id: get_person_name(team, person) for distinct_id, person in persons_by_distinct_id.items()}


def _resolve_date_bounds(
    config: dict[str, Any], team: Team, dashboard_filters: WidgetDashboardFilters
) -> tuple[datetime | None, datetime | None]:
    """A None bound is open, so with no range set stats and responses cover the survey's lifetime."""
    date_from, date_to = dashboard_filters.resolve_date_range(config, None)
    return parse_widget_datetime(date_from, team), parse_widget_datetime(date_to, team, end_of_day=True)


def run_survey_results_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    # Part of the shared run_widgets runner signature (always passed by the dispatcher). This widget
    # reports per-section counts inline rather than a single capped total, so it has nothing to gate.
    include_total_count: bool = True,
    dashboard_filters: WidgetDashboardFilters = NO_DASHBOARD_FILTERS,
) -> dict[str, Any]:
    typed_config = validate_widget_config(SURVEY_RESULTS_WIDGET_TYPE, config)
    survey_id = typed_config.get("surveyId")

    # Honor object-level survey access controls, matching the REST endpoint — a user denied access
    # to a specific survey must not see it (or its responses) through the widget.
    access_control = UserAccessControl(user=user, team=team) if user is not None else None

    if survey_id is None:
        accessible = Survey.objects.filter(team=team, archived=False)
        if access_control is not None:
            accessible = access_control.filter_queryset_by_access_level(accessible)
        return {"survey": None, "responses": [], "needsConfiguration": True, "hasSurveys": accessible.exists()}

    survey_queryset = Survey.objects.filter(id=survey_id, team=team)
    if access_control is not None:
        survey_queryset = access_control.filter_queryset_by_access_level(survey_queryset)
    survey = survey_queryset.first()
    if survey is None:
        return {"survey": None, "responses": [], "surveyNotFound": True}

    since, until = _resolve_date_bounds(typed_config, team, dashboard_filters)

    with tags_context(product=Product.SURVEYS, feature=Feature.QUERY, team_id=team.pk):
        stats_payload = get_survey_stats(
            team_id=team.pk,
            date_from=since.isoformat() if since else None,
            date_to=until.isoformat() if until else None,
            survey_id=str(survey.id),
        )

        rows: list[SurveyResponseRow] = []
        has_more = False
        if survey.start_date is not None:
            # Draft surveys have no responses yet — skip the (bounded-date) responses query.
            rows, has_more = fetch_response_rows(
                survey=survey,
                team=team,
                since=since,
                until=until,
                limit=typed_config["limit"],
            )

    display_names = _resolve_person_display_names(team, rows)

    return {
        "survey": _serialize_survey_summary(survey),
        "stats": stats_payload.get("stats", {}),
        "rates": stats_payload.get("rates", {}),
        "responses": [_serialize_response_row(row, display_names.get(row.distinct_id)) for row in rows],
        "hasMore": has_more,
    }
