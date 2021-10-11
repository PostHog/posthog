import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Union

from typing_extensions import TypedDict

from posthog.event_usage import report_org_usage, report_org_usage_failure
from posthog.models import Event, Team, User
from posthog.tasks.status_report import get_instance_licenses
from posthog.utils import get_instance_realm, get_previous_day, is_clickhouse_enabled
from posthog.version import VERSION

logger = logging.getLogger(__name__)

Period = TypedDict("Period", {"start_inclusive": str, "end_inclusive": str})

OrgReportMetadata = TypedDict(
    "OrgReportMetadata",
    {
        "posthog_version": str,
        "deployment_infrastructure": str,
        "realm": str,
        "is_clickhouse_enabled": bool,
        "period": Period,
        "site_url": str,
        "license_keys": List[str],
    },
)

OrgUsageData = TypedDict(
    "OrgUsageData", {"event_count_lifetime": int, "event_count_in_period": int, "event_count_in_month": int,}
)

OrgReport = TypedDict(
    "OrgReport",
    {
        "posthog_version": str,
        "deployment_infrastructure": str,
        "realm": str,
        "is_clickhouse_enabled": bool,
        "period": Period,
        "site_url": str,
        "license_keys": List[str],
        "event_count_lifetime": int,
        "event_count_in_period": int,
        "event_count_in_month": int,
    },
)  # Repeating the above because mypy doesn't support sum types


def send_all_org_usage_reports(*, dry_run: bool = False) -> List[OrgReport]:
    """
    Creates and sends usage reports for all teams.
    Returns a list of all the successfully sent reports.
    """
    distinct_id = User.objects.first().distinct_id  # type: ignore
    period_start, period_end = get_previous_day()
    month_start = period_start.replace(day=1)
    metadata: OrgReportMetadata = {
        "posthog_version": VERSION,
        "deployment_infrastructure": os.getenv("DEPLOYMENT", "unknown"),
        "realm": get_instance_realm(),
        "is_clickhouse_enabled": is_clickhouse_enabled(),
        "period": {"start_inclusive": period_start.isoformat(), "end_inclusive": period_end.isoformat()},
        "site_url": os.getenv("SITE_URL", "unknown"),
        "license_keys": get_instance_licenses(),
    }
    org_teams: Dict[str, List[Union[str, int]]] = {}
    org_reports: List[OrgReport] = []

    for team in Team.objects.exclude(organization__for_internal_metrics=True):
        org = str(team.organization.id)
        if org in org_teams:
            org_teams[org].append(team.id)
        else:
            org_teams[org] = [team.id]

    for org, teams in org_teams.items():
        usage = get_org_usage(
            distinct_id=distinct_id,
            team_ids=teams,
            period_start=period_start,
            period_end=period_end,
            month_start=month_start,
        )
        report: dict = {
            **metadata,
            **usage,
            "organization_id": org,
        }
        org_reports.append(report)  # type: ignore
        if not dry_run:
            report_org_usage(distinct_id, report)

    return org_reports


def get_org_usage(
    distinct_id: str,
    team_ids: List[Union[str, int]],
    period_start: datetime,
    period_end: datetime,
    month_start: datetime,
) -> OrgUsageData:
    default_usage: OrgUsageData = {
        "event_count_lifetime": 0,
        "event_count_in_period": 0,
        "event_count_in_month": 0,
    }
    usage = default_usage
    try:
        if is_clickhouse_enabled():
            from ee.clickhouse.models.event import (
                get_agg_event_count_for_teams,
                get_agg_event_count_for_teams_and_period,
            )

            usage["event_count_lifetime"] = get_agg_event_count_for_teams(team_ids)
            usage["event_count_in_period"] = get_agg_event_count_for_teams_and_period(
                team_ids, period_start, period_end
            )
            usage["event_count_in_month"] = get_agg_event_count_for_teams_and_period(team_ids, month_start, period_end)
        else:
            usage["event_count_lifetime"] = Event.objects.filter(team_id__in=team_ids).count()
            usage["event_count_in_period"] = Event.objects.filter(
                team_id__in=team_ids, timestamp__gte=period_start, timestamp__lte=period_end,
            ).count()
            usage["event_count_in_month"] = Event.objects.filter(
                team_id__in=team_ids, timestamp__gte=month_start, timestamp__lte=period_end,
            ).count()
    except Exception as err:
        report_org_usage_failure(distinct_id, str(err))

    return usage
