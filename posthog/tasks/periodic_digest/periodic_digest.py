import dataclasses
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog
from celery import shared_task
from dateutil import parser

from posthog.exceptions_capture import capture_exception
from posthog.models.dashboard import Dashboard
from posthog.models.event_definition import EventDefinition
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.models.messaging import MessagingRecord
from posthog.models.organization import OrganizationMembership
from posthog.models.surveys.survey import Survey
from posthog.models.team.team import Team
from posthog.tasks.email import NotificationSetting, NotificationSettingType
from posthog.tasks.periodic_digest.playlist_digests import (
    CountedPlaylist,
    get_teams_with_interesting_playlists,
    get_teams_with_new_playlists,
)
from posthog.tasks.report_utils import OrgDigestReport, TeamDigestReport, capture_event, get_user_team_lookup
from posthog.tasks.usage_report import USAGE_REPORT_TASK_KWARGS, get_instance_metadata, get_ph_client

from products.data_warehouse.backend.models.external_data_source import ExternalDataSource

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class PeriodicDigestReport:
    new_dashboards: list[dict[str, str]]
    new_event_definitions: list[dict[str, str]]
    new_playlists: list[dict[str, str]]
    interesting_collections: list[dict[str, str]]
    interesting_saved_filters: list[dict[str, str]]
    new_experiments_launched: list[dict[str, str]]
    new_experiments_completed: list[dict[str, str]]
    new_external_data_sources: list[dict[str, str]]
    new_surveys_launched: list[dict[str, str]]
    new_feature_flags: list[dict[str, str]]


def get_teams_for_digest() -> list[Team]:
    return list(
        Team.objects.select_related("organization")
        .exclude(Q(organization__for_internal_metrics=True) | Q(is_demo=True))
        .only("id", "name", "organization__id", "organization__name", "organization__created_at")
    )


def get_teams_with_new_dashboards(end: datetime, begin: datetime) -> QuerySet:
    return (
        Dashboard.objects.filter(created_at__gt=begin, created_at__lte=end)
        .exclude(name__contains="Generated Dashboard")
        .values("team_id", "name", "id")
    )


def get_teams_with_new_event_definitions(end: datetime, begin: datetime) -> QuerySet:
    return EventDefinition.objects.filter(created_at__gt=begin, created_at__lte=end).values("team_id", "name", "id")


def get_teams_with_new_experiments_launched(end: datetime, begin: datetime) -> QuerySet:
    return (
        Experiment.objects.filter(
            start_date__gt=begin,
            start_date__lte=end,
        )
        .exclude(
            end_date__gt=begin,
            end_date__lte=end,
        )
        .values("team_id", "name", "id", "start_date")
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


def convert_team_digest_items_to_dict(items: list[CountedPlaylist] | QuerySet) -> dict[int, Any]:
    if hasattr(items, "filter") and hasattr(items, "values_list"):
        # it's a queryset
        return {
            team_id: items.filter(team_id=team_id) for team_id in items.values_list("team_id", flat=True).distinct()
        }
    else:
        # it's a list of CountedPlaylist objects
        grouped = defaultdict(list)
        for item in items:
            grouped[item.team_id].append(item)
        return dict(grouped)


def count_non_zero_digest_items(report: PeriodicDigestReport) -> int:
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
        "teams_with_interesting_playlists": get_teams_with_interesting_playlists(period_end),
        "teams_with_new_experiments_launched": get_teams_with_new_experiments_launched(period_end, period_start),
        "teams_with_new_experiments_completed": get_teams_with_new_experiments_completed(period_end, period_start),
        "teams_with_new_external_data_sources": get_teams_with_new_external_data_sources(period_end, period_start),
        "teams_with_new_surveys_launched": get_teams_with_new_surveys_launched(period_end, period_start),
        "teams_with_new_feature_flags": get_teams_with_new_feature_flags(period_end, period_start),
    }


def get_periodic_digest_report(all_digest_data: dict[str, Any], team: Team) -> PeriodicDigestReport:
    return PeriodicDigestReport(
        new_dashboards=[
            {"name": dashboard.get("name"), "id": dashboard.get("id")}
            for dashboard in all_digest_data["teams_with_new_dashboards"].get(team.id, [])
        ],
        new_event_definitions=[
            {"name": event_definition.get("name"), "id": event_definition.get("id")}
            for event_definition in all_digest_data["teams_with_new_event_definitions"].get(team.id, [])
        ],
        new_playlists=[
            {
                "name": playlist.name or playlist.derived_name or "Untitled",
                "id": playlist.short_id,
                "type": playlist.type,
                "count": playlist.count,
                "has_more_available": playlist.has_more_available,
                "url_path": playlist.url_path,
            }
            for playlist in all_digest_data["teams_with_new_playlists"].get(team.id, [])
        ],
        interesting_collections=[
            {
                "name": playlist.name or playlist.derived_name or "Untitled",
                "id": playlist.short_id,
                "type": playlist.type,
                "count": playlist.count,
                "has_more_available": playlist.has_more_available,
                "url_path": playlist.url_path,
            }
            for playlist in all_digest_data["teams_with_interesting_playlists"].get(team.id, [])
            if playlist.type == "collection"
        ],
        interesting_saved_filters=[
            {
                "name": playlist.name or playlist.derived_name or "Untitled",
                "id": playlist.short_id,
                "type": playlist.type,
                "count": playlist.count,
                "has_more_available": playlist.has_more_available,
                "url_path": playlist.url_path,
            }
            for playlist in all_digest_data["teams_with_interesting_playlists"].get(team.id, [])
            if playlist.type == "filters"
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


def _get_all_org_digest_reports(period_start: datetime, period_end: datetime) -> dict[str, OrgDigestReport]:
    """
    Gets all digest data and organizes it by organization
    """
    logger.info("Getting all digest data...")
    time_now = datetime.now()
    all_digest_data = _get_all_digest_data_as_team_rows(period_start, period_end)
    logger.debug(f"Getting all digest data took {(datetime.now() - time_now).total_seconds()} seconds.")

    logger.info("Getting teams for digest reports...")
    time_now = datetime.now()
    teams = get_teams_for_digest()
    logger.debug(f"Getting teams for digest reports took {(datetime.now() - time_now).total_seconds()} seconds.")

    org_reports: dict[str, OrgDigestReport] = {}

    logger.info("Generating reports for organizations...")
    time_now = datetime.now()

    for team in teams:
        org_id = str(team.organization_id)
        if org_id not in org_reports:
            org_reports[org_id] = OrgDigestReport(
                organization_id=org_id,
                organization_name=team.organization.name,
                organization_created_at=team.organization.created_at.isoformat(),
                teams=[],
                total_digest_items_with_data=0,
            )

        team_report = get_periodic_digest_report(all_digest_data, team)
        if count_non_zero_digest_items(team_report) > 0:  # Only include teams with data
            org_reports[org_id].teams.append(
                TeamDigestReport(
                    team_id=team.id,
                    team_name=team.name,
                    report=dataclasses.asdict(team_report),
                    digest_items_with_data=count_non_zero_digest_items(team_report),
                )
            )

    time_since = datetime.now() - time_now
    logger.debug(f"Generating reports for organizations took {time_since.total_seconds()} seconds.")
    return org_reports


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
        org_reports = _get_all_org_digest_reports(period_start, period_end)
        instance_metadata = dataclasses.asdict(get_instance_metadata((period_start, period_end)))

        logger.info("Sending digest reports...")
        time_now = datetime.now()

        for org_id, org_report in org_reports.items():
            if not org_report.teams:  # Skip if no teams have data
                continue

            if dry_run:
                continue

            # Get user access and notification preferences
            user_teams, user_notifications = get_user_team_lookup(org_id)

            # Check if we've already sent this digest
            period_str = period_end.strftime("%Y-%m-%d")
            days = (period_end - period_start).days
            campaign_key = f"periodic_digest_{period_str}_{days}d"

            record, created = MessagingRecord.objects.get_or_create(
                raw_email=f"org_{org_id}", campaign_key=campaign_key
            )

            if not created and record.sent_at:
                logger.info(f"Skipping duplicate periodic digest for org {org_id}")
                continue

            # Get all org members
            org_members = OrganizationMembership.objects.filter(organization_id=org_id).select_related("user")
            # Send customized report to each user
            for membership in org_members:
                user = membership.user
                user_team_ids = user_teams.get(user.id, set())
                user_notif_team_ids = user_notifications.get(user.id, set())

                # Filter report to only include teams the user has access to
                user_report = org_report.filter_for_user(user_team_ids, user_notif_team_ids)

                if not user_report.teams or not user.distinct_id:
                    continue

                report_dict = dataclasses.asdict(user_report)
                send_digest_notifications(
                    organization_id=org_id,
                    event_name="transactional email",
                    properties={
                        **report_dict,
                        **instance_metadata,
                        "template_name": "periodic_digest_report",
                    },
                    notification_type=NotificationSetting.WEEKLY_PROJECT_DIGEST.value,
                    distinct_id=user.distinct_id,
                )

            # Mark as sent
            record.sent_at = timezone.now()
            record.save()

        time_since = datetime.now() - time_now
        logger.debug(f"Sending digest reports took {time_since.total_seconds()} seconds.")

    except Exception as err:
        capture_exception(err)
        raise


def send_digest_notifications(
    *,
    organization_id: str,
    event_name: str,
    properties: dict[str, Any],
    notification_type: NotificationSettingType,
    timestamp: Optional[datetime] = None,
    distinct_id: str,
) -> None:
    """
    Sends a single notification for digest reports.
    """

    capture_event(
        pha_client=get_ph_client(),
        name=event_name,
        organization_id=organization_id,
        team_id=None,
        properties=properties,
        timestamp=timestamp,
        distinct_id=distinct_id,
    )
    get_ph_client().group_identify("organization", organization_id, properties)
