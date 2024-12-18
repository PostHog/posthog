import dataclasses
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import structlog
from celery import shared_task
from dateutil import parser
from django.db.models import QuerySet
from django.utils import timezone
from sentry_sdk import capture_exception

from posthog.models.dashboard import Dashboard
from posthog.models.event_definition import EventDefinition
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.models.feedback.survey import Survey
from posthog.models.messaging import MessagingRecord
from posthog.models.team.team import Team
from posthog.session_recordings.models.session_recording_playlist import (
    SessionRecordingPlaylist,
)
from posthog.tasks.usage_report import (
    USAGE_REPORT_TASK_KWARGS,
    capture_report,
    get_instance_metadata,
)
from posthog.tasks.utils import CeleryQueue
from posthog.warehouse.models.external_data_source import ExternalDataSource

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class periodicDigestReport:
    new_dashboards: list[dict[str, str]]
    new_event_definitions: list[dict[str, str]]
    new_playlists: list[dict[str, str]]
    new_experiments_launched: list[dict[str, str]]
    new_experiments_completed: list[dict[str, str]]
    new_external_data_sources: list[dict[str, str]]
    new_surveys_launched: list[dict[str, str]]
    new_feature_flags: list[dict[str, str]]


def get_teams_for_digest() -> list[Team]:
    from django.db.models import Q

    return list(
        Team.objects.select_related("organization")
        .exclude(Q(organization__for_internal_metrics=True) | Q(is_demo=True))
        .only("id", "name", "organization__id", "organization__name", "organization__created_at")
    )


def get_teams_with_new_dashboards(end: datetime, begin: datetime) -> QuerySet:
    return Dashboard.objects.filter(created_at__gt=begin, created_at__lte=end).values("team_id", "name", "id")


def get_teams_with_new_event_definitions(end: datetime, begin: datetime) -> QuerySet:
    return EventDefinition.objects.filter(created_at__gt=begin, created_at__lte=end).values("team_id", "name", "id")


def get_teams_with_new_playlists(end: datetime, begin: datetime) -> QuerySet:
    return SessionRecordingPlaylist.objects.filter(created_at__gt=begin, created_at__lte=end).values(
        "team_id", "name", "short_id"
    )


def get_teams_with_new_experiments_launched(end: datetime, begin: datetime) -> QuerySet:
    return Experiment.objects.filter(start_date__gt=begin, start_date__lte=end).values(
        "team_id", "name", "id", "start_date"
    )


def get_teams_with_new_experiments_completed(end: datetime, begin: datetime) -> QuerySet:
    return Experiment.objects.filter(end_date__gt=begin, end_date__lte=end).values(
        "team_id", "name", "id", "start_date", "end_date"
    )


def get_teams_with_new_external_data_sources(end: datetime, begin: datetime) -> QuerySet:
    return ExternalDataSource.objects.filter(created_at__gt=begin, created_at__lte=end, deleted=False).values(
        "team_id", "source_type", "id"
    )


def get_teams_with_new_surveys_launched(end: datetime, begin: datetime) -> QuerySet:
    return Survey.objects.filter(start_date__gt=begin, start_date__lte=end).values(
        "team_id", "name", "id", "description", "start_date"
    )


def get_teams_with_new_feature_flags(end: datetime, begin: datetime) -> QuerySet:
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


def count_non_zero_digest_items(report: periodicDigestReport) -> int:
    return sum(1 for key in report.__dataclass_fields__ if len(getattr(report, key)) > 0)


def _get_all_digest_data_as_team_rows(period_start: datetime, period_end: datetime) -> dict[str, Any]:
    all_digest_data = _get_all_digest_data(period_start, period_end)
    # convert it to a map of team_id -> value
    for key, rows in all_digest_data.items():
        all_digest_data[key] = convert_team_digest_items_to_dict(rows)
    return all_digest_data


def _get_all_digest_data(period_start: datetime, period_end: datetime) -> dict[str, Any]:
    return {
        "teams_with_new_dashboards": get_teams_with_new_dashboards(period_end, period_start),
        "teams_with_new_event_definitions": get_teams_with_new_event_definitions(period_end, period_start),
        "teams_with_new_playlists": get_teams_with_new_playlists(period_end, period_start),
        "teams_with_new_experiments_launched": get_teams_with_new_experiments_launched(period_end, period_start),
        "teams_with_new_experiments_completed": get_teams_with_new_experiments_completed(period_end, period_start),
        "teams_with_new_external_data_sources": get_teams_with_new_external_data_sources(period_end, period_start),
        "teams_with_new_surveys_launched": get_teams_with_new_surveys_launched(period_end, period_start),
        "teams_with_new_feature_flags": get_teams_with_new_feature_flags(period_end, period_start),
    }


def get_periodic_digest_report(all_digest_data: dict[str, Any], team: Team) -> periodicDigestReport:
    return periodicDigestReport(
        new_dashboards=[
            {"name": dashboard.get("name"), "id": dashboard.get("id")}
            for dashboard in all_digest_data["teams_with_new_dashboards"].get(team.id, [])
        ],
        new_event_definitions=[
            {"name": event_definition.get("name"), "id": event_definition.get("id")}
            for event_definition in all_digest_data["teams_with_new_event_definitions"].get(team.id, [])
        ],
        new_playlists=[
            {"name": playlist.get("name"), "id": playlist.get("short_id")}
            for playlist in all_digest_data["teams_with_new_playlists"].get(team.id, [])
        ],
        new_experiments_launched=[
            {
                "name": experiment.get("name"),
                "id": experiment.get("id"),
                "start_date": experiment.get("start_date").isoformat(),
            }
            for experiment in all_digest_data["teams_with_new_experiments_launched"].get(team.id, [])
        ],
        new_experiments_completed=[
            {
                "name": experiment.get("name"),
                "id": experiment.get("id"),
                "start_date": experiment.get("start_date").isoformat(),
                "end_date": experiment.get("end_date").isoformat(),
            }
            for experiment in all_digest_data["teams_with_new_experiments_completed"].get(team.id, [])
        ],
        new_external_data_sources=[
            {"source_type": source.get("source_type"), "id": source.get("id")}
            for source in all_digest_data["teams_with_new_external_data_sources"].get(team.id, [])
        ],
        new_surveys_launched=[
            {
                "name": survey.get("name"),
                "id": survey.get("id"),
                "start_date": survey.get("start_date").isoformat(),
                "description": survey.get("description"),
            }
            for survey in all_digest_data["teams_with_new_surveys_launched"].get(team.id, [])
        ],
        new_feature_flags=[
            {"name": feature_flag.get("name"), "id": feature_flag.get("id"), "key": feature_flag.get("key")}
            for feature_flag in all_digest_data["teams_with_new_feature_flags"].get(team.id, [])
        ],
    )


@shared_task(queue=CeleryQueue.USAGE_REPORTS.value, ignore_result=True, max_retries=3)
def send_periodic_digest_report(
    *,
    team_id: int,
    team_name: str,
    periodic_digest_report: dict[str, Any],
    instance_metadata: dict[str, Any],
    period_end: datetime,
    period_start: datetime,
    digest_items_with_data: int,
) -> None:
    period_str = period_end.strftime("%Y-%m-%d")
    days = (period_end - period_start).days
    campaign_key = f"periodic_digest_{period_str}_{days}d"

    # Use a consistent identifier for the team
    team_identifier = f"team_{team_id}"

    # Check if we've already sent this digest using get_or_create
    record, created = MessagingRecord.objects.get_or_create(raw_email=team_identifier, campaign_key=campaign_key)

    if not created and record.sent_at:
        logger.info(f"Skipping duplicate periodic digest for team {team_id} for period ending {period_str}")
        return

    full_report_dict = {
        "team_id": team_id,
        "team_name": team_name,
        "template_name": "periodic_digest_report",
        "digest_items_with_data": digest_items_with_data,
        **periodic_digest_report,
        **instance_metadata,
    }

    capture_report.delay(
        capture_event_name="transactional email",
        team_id=team_id,
        full_report_dict=full_report_dict,
        send_for_all_members=True,
    )

    # Mark as sent
    record.sent_at = timezone.now()
    record.save()


@shared_task(**USAGE_REPORT_TASK_KWARGS, max_retries=0)
def send_all_periodic_digest_reports(
    dry_run: bool = False,
    end_date: Optional[str] = None,
    begin_date: Optional[str] = None,
) -> None:
    period_end = (
        parser.parse(end_date)
        if end_date
        else datetime.now(tz=ZoneInfo("UTC")).replace(hour=0, minute=0, second=0, microsecond=0)
    )
    period_start = parser.parse(begin_date) if begin_date else period_end - timedelta(days=7)

    try:
        all_digest_data = _get_all_digest_data_as_team_rows(period_start, period_end)
        teams = get_teams_for_digest()
        time_now = datetime.now()
        for team in teams:
            report = get_periodic_digest_report(all_digest_data, team)
            full_report_dict = dataclasses.asdict(report)
            instance_metadata = dataclasses.asdict(get_instance_metadata((period_start, period_end)))
            digest_items_with_data = count_non_zero_digest_items(report)

            # Then capture as events to PostHog, so they can be sent via email
            if digest_items_with_data > 0 and not dry_run:
                send_periodic_digest_report.delay(
                    team_id=team.id,
                    team_name=team.name,
                    periodic_digest_report=full_report_dict,
                    instance_metadata=instance_metadata,
                    period_end=period_end,
                    period_start=period_start,
                    digest_items_with_data=digest_items_with_data,
                )
        time_since = datetime.now() - time_now
        logger.debug(f"Sending usage reports to PostHog and Billing took {time_since.total_seconds()} seconds.")  # noqa T201
    except Exception as err:
        capture_exception(err)
        raise
