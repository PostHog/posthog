import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Literal, Optional, TypedDict, Union, cast

from django.conf import settings
from django.db.models.manager import BaseManager
from sentry_sdk import capture_exception

from posthog.event_usage import report_org_usage, report_org_usage_failure
from posthog.models import Event, OrganizationMembership, Team, User
from posthog.tasks.status_report import get_instance_licenses
from posthog.utils import get_instance_realm, get_previous_day, is_clickhouse_enabled
from posthog.version import VERSION

logger = logging.getLogger(__name__)

Period = TypedDict("Period", {"start_inclusive": str, "end_inclusive": str})

OrgData = TypedDict("OrgData", {"teams": List[Union[str, int]], "user_count": int, "name": str, "created_at": str,},)

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
        "product": str,
    },
)

OrgUsageData = TypedDict(
    "OrgUsageData",
    {
        "event_count_lifetime": Optional[int],
        "event_count_in_period": Optional[int],
        "event_count_in_month": Optional[int],
    },
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
        "organization_id": str,
        "organization_name": str,
        "organization_created_at": str,
        "organization_user_count": int,
        "team_count": int,
        "product": str,
    },
)


def send_all_org_usage_reports(*, dry_run: bool = False) -> List[OrgReport]:
    """
    Creates and sends usage reports for all teams.
    Returns a list of all the successfully sent reports.
    """
    return send_all_reports(dry_run=dry_run, data_source="postgres")


def send_all_reports(
    *, dry_run: bool = False, data_source: Literal["clickhouse", "postgres"] = "postgres"
) -> List[OrgReport]:
    """
    Generic way to generate and send org usage reports.
    Specify Postgres or ClickHouse for event queries.
    """
    period_start, period_end = get_previous_day()
    realm = get_instance_realm()
    license_keys = get_instance_licenses()
    metadata: OrgReportMetadata = {
        "posthog_version": VERSION,
        "deployment_infrastructure": os.getenv("DEPLOYMENT", "unknown"),
        "realm": realm,
        "is_clickhouse_enabled": is_clickhouse_enabled(),
        "period": {"start_inclusive": period_start.isoformat(), "end_inclusive": period_end.isoformat()},
        "site_url": os.getenv("SITE_URL", "unknown"),
        "license_keys": license_keys,
        "product": get_product_name(realm, license_keys),
    }
    org_data: Dict[str, OrgData] = {}
    org_reports: List[OrgReport] = []

    for team in Team.objects.exclude(organization__for_internal_metrics=True):
        org = team.organization
        id = str(org.id)
        if id in org_data:
            org_data[id]["teams"].append(team.id)
        else:
            org_data[id] = {
                "teams": [team.id],
                "user_count": get_org_user_count(id),
                "name": org.name,
                "created_at": str(org.created_at),
            }

    for id, org in org_data.items():
        org_owner = get_org_owner_or_first_user(id)
        if not org_owner:
            continue
        distinct_id = org_owner.distinct_id
        try:
            month_start = period_start.replace(day=1)
            usage = get_org_usage(
                team_ids=org["teams"],
                period_start=period_start,
                period_end=period_end,
                month_start=month_start,
                data_source=data_source,
            )
            report: dict = {
                **metadata,
                **usage,
                "organization_id": id,
                "organization_name": org["name"],
                "organization_created_at": org["created_at"],
                "organization_user_count": org["user_count"],
                "team_count": len(org["teams"]),
            }
            org_reports.append(report)  # type: ignore
        except Exception as err:
            report_org_usage_failure(distinct_id, str(err))
        if not (dry_run or settings.TEST or settings.DEBUG):
            report_org_usage(distinct_id, report)
            time.sleep(0.25)

    return org_reports


def get_org_usage(
    team_ids: List[Union[str, int]],
    period_start: datetime,
    period_end: datetime,
    month_start: datetime,
    data_source: Literal["clickhouse", "postgres"] = "postgres",
) -> OrgUsageData:
    default_usage: OrgUsageData = {
        "event_count_lifetime": None,
        "event_count_in_period": None,
        "event_count_in_month": None,
    }
    usage = default_usage
    if data_source == "clickhouse":
        from ee.clickhouse.models.event import get_agg_event_count_for_teams, get_agg_event_count_for_teams_and_period

        usage["event_count_lifetime"] = get_agg_event_count_for_teams(team_ids)
        usage["event_count_in_period"] = get_agg_event_count_for_teams_and_period(team_ids, period_start, period_end)
        usage["event_count_in_month"] = get_agg_event_count_for_teams_and_period(team_ids, month_start, period_end)
    else:
        usage["event_count_lifetime"] = Event.objects.filter(team_id__in=team_ids).count()
        usage["event_count_in_period"] = Event.objects.filter(
            team_id__in=team_ids, timestamp__gte=period_start, timestamp__lte=period_end,
        ).count()
        usage["event_count_in_month"] = Event.objects.filter(
            team_id__in=team_ids, timestamp__gte=month_start, timestamp__lte=period_end,
        ).count()

    return usage


def get_product_name(realm: str, license_keys: List[str]) -> str:
    if realm == "cloud":
        return "cloud"
    elif realm in {"hosted", "hosted-clickhouse"}:
        return "scale" if len(license_keys) else "open source"
    else:
        return "unknown"


def get_org_memberships(organization_id: str) -> BaseManager:
    return OrganizationMembership.objects.filter(organization_id=organization_id)


def get_org_user_count(organization_id: str) -> int:
    return get_org_memberships(organization_id=organization_id).count()


def get_org_owner_or_first_user(organization_id: str) -> Optional[User]:
    # Find the membership object for the org owner
    user = None
    membership = (
        get_org_memberships(organization_id=organization_id).filter(level=OrganizationMembership.Level.OWNER).first()
    )
    if not membership:
        # If no owner membership is present, pick the first membership association we can find
        membership = OrganizationMembership.objects.filter(organization_id=organization_id).first()
    if hasattr(membership, "user"):
        membership = cast(OrganizationMembership, membership)
        user = membership.user
    else:
        capture_exception(
            Exception("No user found for org while generating report"), {"org": {"organization_id": organization_id}},
        )
    return user
