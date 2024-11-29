import dataclasses
from datetime import datetime, timedelta
from typing import Any, Optional

import structlog
from celery import shared_task
from dateutil import parser
from django.db.models import QuerySet
from sentry_sdk import capture_exception

from posthog.models.dashboard import Dashboard
from posthog.models.event_definition import EventDefinition
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.models.feedback.survey import Survey
from posthog.models.team.team import Team
from posthog.session_recordings.models.session_recording_playlist import (
    SessionRecordingPlaylist,
)
from posthog.tasks.usage_report import USAGE_REPORT_TASK_KWARGS, capture_report
from posthog.tasks.utils import CeleryQueue
from posthog.utils import get_previous_day
from posthog.warehouse.models.external_data_source import ExternalDataSource

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class WeeklyDigestReport:
    new_dashboards_in_last_7_days: list[dict[str, str]]
    new_event_definitions_in_last_7_days: list[dict[str, str]]
    new_playlists_created_in_last_7_days: list[dict[str, str]]
    new_experiments_launched_in_last_7_days: list[dict[str, str]]
    new_experiments_completed_in_last_7_days: list[dict[str, str]]
    new_external_data_sources_connected_in_last_7_days: list[dict[str, str]]
    new_surveys_launched_in_last_7_days: list[dict[str, str]]
    new_feature_flags_created_in_last_7_days: list[dict[str, str]]


def get_teams_for_digest() -> list[Team]:
    from django.db.models import Q

    return list(
        Team.objects.select_related("organization")
        .exclude(Q(organization__for_internal_metrics=True) | Q(is_demo=True))
        .only("id", "name", "organization__id", "organization__name", "organization__created_at")
    )


def get_teams_with_new_dashboards_in_last_7_days(end: datetime) -> QuerySet:
    begin = end - timedelta(days=7)
    return Dashboard.objects.filter(created_at__gt=begin, created_at__lte=end).values("team_id", "name", "id")


def get_teams_with_new_event_definitions_in_last_7_days(end: datetime) -> QuerySet:
    begin = end - timedelta(days=7)
    return EventDefinition.objects.filter(created_at__gt=begin, created_at__lte=end).values("team_id", "name", "id")


def get_teams_with_new_playlists_created_in_last_7_days(end: datetime) -> QuerySet:
    begin = end - timedelta(days=7)
    return SessionRecordingPlaylist.objects.filter(created_at__gt=begin, created_at__lte=end).values(
        "team_id", "name", "short_id"
    )


def get_teams_with_new_experiments_launched_in_last_7_days(end: datetime) -> QuerySet:
    begin = end - timedelta(days=7)
    return Experiment.objects.filter(start_date__gt=begin, start_date__lte=end).values(
        "team_id", "name", "id", "start_date"
    )


def get_teams_with_new_experiments_completed_in_last_7_days(end: datetime) -> QuerySet:
    begin = end - timedelta(days=7)
    return Experiment.objects.filter(end_date__gt=begin, end_date__lte=end).values(
        "team_id", "name", "id", "start_date", "end_date"
    )


def get_teams_with_new_external_data_sources_connected_in_last_7_days(end: datetime) -> QuerySet:
    begin = end - timedelta(days=7)
    return ExternalDataSource.objects.filter(created_at__gt=begin, created_at__lte=end, deleted=False).values(
        "team_id", "source_type", "id"
    )


def get_teams_with_new_surveys_launched_in_last_7_days(end: datetime) -> QuerySet:
    begin = end - timedelta(days=7)
    return Survey.objects.filter(start_date__gt=begin, start_date__lte=end).values(
        "team_id", "name", "id", "description", "start_date"
    )


def get_teams_with_new_feature_flags_created_in_last_7_days(end: datetime) -> QuerySet:
    begin = end - timedelta(days=7)
    return (
        FeatureFlag.objects.filter(
            created_at__gt=begin,
            created_at__lte=end,
            deleted=False,
        )
        .exclude(name__contains="Feature Flag for Experiment")
        .exclude(name__contains="Targeting flag for survey")
        .values("team_id", "name", "id", "key")
    )


def convert_team_digest_items_to_dict(items: QuerySet) -> dict[int, QuerySet]:
    return {team_id: items.filter(team_id=team_id) for team_id in items.values_list("team_id", flat=True).distinct()}


def has_non_zero_digest(report: WeeklyDigestReport) -> bool:
    return any(len(getattr(report, key)) > 0 for key in report.__dataclass_fields__)


def _get_all_digest_data_as_team_rows(period_start: datetime, period_end: datetime) -> dict[str, Any]:
    all_digest_data = _get_all_digest_data(period_start, period_end)
    # convert it to a map of team_id -> value
    for key, rows in all_digest_data.items():
        all_digest_data[key] = convert_team_digest_items_to_dict(rows)
    return all_digest_data


def _get_all_digest_data(period_start: datetime, period_end: datetime) -> dict[str, Any]:
    return {
        "teams_with_new_dashboards_in_last_7_days": get_teams_with_new_dashboards_in_last_7_days(period_end),
        "teams_with_new_event_definitions_in_last_7_days": get_teams_with_new_event_definitions_in_last_7_days(
            period_end
        ),
        "teams_with_new_playlists_created_in_last_7_days": get_teams_with_new_playlists_created_in_last_7_days(
            period_end
        ),
        "teams_with_new_experiments_launched_in_last_7_days": get_teams_with_new_experiments_launched_in_last_7_days(
            period_end
        ),
        "teams_with_new_experiments_completed_in_last_7_days": get_teams_with_new_experiments_completed_in_last_7_days(
            period_end
        ),
        "teams_with_new_external_data_sources_connected_in_last_7_days": get_teams_with_new_external_data_sources_connected_in_last_7_days(
            period_end
        ),
        "teams_with_new_surveys_launched_in_last_7_days": get_teams_with_new_surveys_launched_in_last_7_days(
            period_end
        ),
        "teams_with_new_feature_flags_created_in_last_7_days": get_teams_with_new_feature_flags_created_in_last_7_days(
            period_end
        ),
    }


def get_weekly_digest_report(all_digest_data: dict[str, Any], team: Team) -> WeeklyDigestReport:
    return WeeklyDigestReport(
        new_dashboards_in_last_7_days=[
            {"name": dashboard.get("name"), "id": dashboard.get("id")}
            for dashboard in all_digest_data["teams_with_new_dashboards_in_last_7_days"].get(team.id, [])
        ],
        new_event_definitions_in_last_7_days=[
            {"name": event_definition.get("name"), "id": event_definition.get("id")}
            for event_definition in all_digest_data["teams_with_new_event_definitions_in_last_7_days"].get(team.id, [])
        ],
        new_playlists_created_in_last_7_days=[
            {"name": playlist.get("name"), "id": playlist.get("short_id")}
            for playlist in all_digest_data["teams_with_new_playlists_created_in_last_7_days"].get(team.id, [])
        ],
        new_experiments_launched_in_last_7_days=[
            {
                "name": experiment.get("name"),
                "id": experiment.get("id"),
                "start_date": experiment.get("start_date").isoformat(),
            }
            for experiment in all_digest_data["teams_with_new_experiments_launched_in_last_7_days"].get(team.id, [])
        ],
        new_experiments_completed_in_last_7_days=[
            {
                "name": experiment.get("name"),
                "id": experiment.get("id"),
                "start_date": experiment.get("start_date").isoformat(),
                "end_date": experiment.get("end_date").isoformat(),
            }
            for experiment in all_digest_data["teams_with_new_experiments_completed_in_last_7_days"].get(team.id, [])
        ],
        new_external_data_sources_connected_in_last_7_days=[
            {"source_type": source.get("source_type"), "id": source.get("id")}
            for source in all_digest_data["teams_with_new_external_data_sources_connected_in_last_7_days"].get(
                team.id, []
            )
        ],
        new_surveys_launched_in_last_7_days=[
            {
                "name": survey.get("name"),
                "id": survey.get("id"),
                "start_date": survey.get("start_date").isoformat(),
                "description": survey.get("description"),
            }
            for survey in all_digest_data["teams_with_new_surveys_launched_in_last_7_days"].get(team.id, [])
        ],
        new_feature_flags_created_in_last_7_days=[
            {"name": feature_flag.get("name"), "id": feature_flag.get("id"), "key": feature_flag.get("key")}
            for feature_flag in all_digest_data["teams_with_new_feature_flags_created_in_last_7_days"].get(team.id, [])
        ],
    )


@shared_task(queue=CeleryQueue.USAGE_REPORTS.value, ignore_result=True, max_retries=3)
def send_weekly_digest_report(*, team_id: int, team_name: str, weekly_digest_report: dict[str, Any]) -> None:
    full_report_dict = {
        "team_id": team_id,
        "team_name": team_name,
        "template": "weekly_digest_report",
        **weekly_digest_report,
    }
    capture_report.delay(
        capture_event_name="transactional email",
        team_id=team_id,
        full_report_dict=full_report_dict,
        send_for_all_members=True,
    )


@shared_task(**USAGE_REPORT_TASK_KWARGS, max_retries=0)
def send_all_weekly_digest_reports(
    dry_run: bool = False,
    at: Optional[str] = None,
) -> None:
    at_date = parser.parse(at) if at else None
    period = get_previous_day(at=at_date)
    period_start, period_end = period

    try:
        all_digest_data = _get_all_digest_data_as_team_rows(period_start, period_end)
        teams = get_teams_for_digest()
        time_now = datetime.now()
        for team in teams:
            report = get_weekly_digest_report(all_digest_data, team)
            full_report_dict = dataclasses.asdict(report)

            # Then capture as events to PostHog, so they can be sent via email
            if has_non_zero_digest(report) and not dry_run:
                send_weekly_digest_report.delay(
                    team_id=team.id, team_name=team.name, weekly_digest_report=full_report_dict
                )
        time_since = datetime.now() - time_now
        logger.debug(f"Sending usage reports to PostHog and Billing took {time_since.total_seconds()} seconds.")  # noqa T201
    except Exception as err:
        capture_exception(err)
        raise
