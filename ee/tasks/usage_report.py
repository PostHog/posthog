import json
import os
import time
from collections import Counter
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    TypedDict,
    Union,
    cast,
)

import posthoganalytics
import requests
import structlog
from django.conf import settings
from django.db import connection
from django.db.models.manager import BaseManager
from psycopg2 import sql
from sentry_sdk import capture_exception
from typing_extensions import NotRequired

from ee.api.billing import build_billing_token
from ee.models.license import License
from ee.settings import BILLING_SERVICE_URL
from posthog import version_requirement
from posthog.cloud_utils import is_cloud
from posthog.models import GroupTypeMapping, OrganizationMembership, Person, Team, User
from posthog.models.dashboard import Dashboard
from posthog.models.event.util import (
    get_event_count_for_team,
    get_event_count_for_team_and_period,
    get_event_count_with_groups_count_for_team_and_period,
    get_events_count_for_team_by_client_lib,
    get_events_count_for_team_by_event_type,
)
from posthog.models.feature_flag import FeatureFlag
from posthog.models.person.util import count_duplicate_distinct_ids_for_team, count_total_persons_with_multiple_ids
from posthog.models.plugin import PluginConfig
from posthog.models.session_recording_event.util import get_recording_count_for_team_and_period
from posthog.models.utils import namedtuplefetchall
from posthog.utils import get_helm_info_env, get_instance_realm, get_machine_id, get_previous_day
from posthog.version import VERSION

logger = structlog.get_logger(__name__)

Period = TypedDict("Period", {"start_inclusive": str, "end_inclusive": str})

TeamUsageReport = TypedDict(
    "TeamUsageReport",
    {
        "event_count_total": int,
        "event_count_new_in_period": int,
        "event_count_with_groups_new_in_period": int,
        "event_count_by_lib": Dict,
        "event_count_by_name": Dict,
        "recording_count_new_in_period": int,
        "duplicate_distinct_ids": Dict,
        "multiple_ids_per_person": Dict,
        "group_types_total": int,
        "person_count_total": int,
        "person_count_new_in_period": int,
        "dashboard_count": int,
        "dashboard_template_count": int,
        "dashboard_shared_count": int,
        "dashboard_tagged_count": int,
        "ff_count": int,
        "ff_active_count": int,
    },
)

OrgUsageSummary = TypedDict(
    "OrgUsageSummary",
    {
        "event_count_new_in_period": int,
        "person_count_new_in_period": int,
        "person_count_total": int,
        "event_count_total": int,
        "event_count_with_groups_new_in_period": int,
        "recording_count_new_in_period": int,
        "dashboard_count": int,
        "ff_count": int,
        "using_groups": bool,
    },
)

OrgUsageReport = TypedDict(
    "OrgUsageReport",
    {
        "org_usage_summary": OrgUsageSummary,
        "teams": Dict[str, TeamUsageReport],
    },
)

TableSizes = TypedDict("TableSizes", {"posthog_event": int, "posthog_sessionrecordingevent": int})

OrgMetadata = TypedDict(
    "OrgMetadata",
    {
        "posthog_version": str,
        "deployment_infrastructure": str,
        "realm": str,
        "period": Period,
        "site_url": str,
        "product": str,
        "helm": NotRequired[dict],
        "clickhouse_version": NotRequired[str],
        "users_who_logged_in": NotRequired[List[Dict[str, Union[str, int]]]],
        "users_who_logged_in_count": NotRequired[int],
        "users_who_signed_up": NotRequired[List[Dict[str, Union[str, int]]]],
        "users_who_signed_up_count": NotRequired[int],
        "table_sizes": NotRequired[TableSizes],
        "plugins_installed": NotRequired["Counter"],
        "plugins_enabled": NotRequired["Counter"],
    },
)

OrgReport = TypedDict(
    "OrgReport",
    {
        "date": str,
        "admin_distinct_id": int,
        "organization_id": str,
        "organization_name": str,
        "organization_created_at": str,
        "organization_user_count": int,
        "posthog_version": str,
        "deployment_infrastructure": str,
        "realm": str,
        "period": Period,
        "site_url": str,
        "product": str,
        "helm": NotRequired[dict],
        "clickhouse_version": NotRequired[str],
        "users_who_logged_in": NotRequired[List[Dict[str, Union[str, int]]]],
        "users_who_logged_in_count": NotRequired[int],
        "users_who_signed_up": NotRequired[List[Dict[str, Union[str, int]]]],
        "users_who_signed_up_count": NotRequired[int],
        "table_sizes": NotRequired[TableSizes],
        "plugins_installed": NotRequired["Counter"],
        "plugins_enabled": NotRequired["Counter"],
        "team_count": int,
        "org_usage_summary": OrgUsageSummary,
        "teams": Dict[str, TeamUsageReport],
    },
)


def send_all_org_usage_reports(*, dry_run: bool = False) -> List[OrgReport]:
    """
    Creates and sends usage reports for all teams.
    Returns a list of all the successfully sent reports.
    """
    return send_all_reports(dry_run=dry_run)


def get_org_usage_report(organization_id: str, team_ids: List[str], dry_run: bool) -> OrgUsageReport:
    period_start, period_end = get_previous_day()

    org_usage_summary: OrgUsageSummary = {
        "event_count_new_in_period": 0,
        "person_count_new_in_period": 0,
        "person_count_total": 0,
        "event_count_total": 0,
        "event_count_with_groups_new_in_period": 0,
        "recording_count_new_in_period": 0,
        "dashboard_count": 0,
        "ff_count": 0,
        "using_groups": False,
    }
    teams: Dict[str, TeamUsageReport] = {}

    for team_id in team_ids:
        try:
            # pull person stats and the rest here from Postgres always
            persons_considered_total = Person.objects.filter(team_id=team_id)
            persons_considered_total_new_in_period = persons_considered_total.filter(
                created_at__gte=period_start, created_at__lte=period_end
            )

            # Dashboards
            team_dashboards = Dashboard.objects.filter(team_id=team_id).exclude(deleted=True)

            # Feature Flags
            feature_flags = FeatureFlag.objects.filter(team_id=team_id).exclude(deleted=True)

            team_report: TeamUsageReport = {
                "event_count_total": get_event_count_for_team(team_id),
                "event_count_new_in_period": get_event_count_for_team_and_period(team_id, period_start, period_end),
                "event_count_with_groups_new_in_period": get_event_count_with_groups_count_for_team_and_period(
                    team_id, period_start, period_end
                ),
                "event_count_by_lib": get_events_count_for_team_by_client_lib(team_id, period_start, period_end),
                "event_count_by_name": get_events_count_for_team_by_event_type(team_id, period_start, period_end),
                "recording_count_new_in_period": get_recording_count_for_team_and_period(
                    team_id, period_start, period_end
                ),
                "duplicate_distinct_ids": count_duplicate_distinct_ids_for_team(team_id),
                "multiple_ids_per_person": count_total_persons_with_multiple_ids(team_id),
                "group_types_total": GroupTypeMapping.objects.filter(team_id=team_id).count(),
                "person_count_total": persons_considered_total.count(),
                "person_count_new_in_period": persons_considered_total_new_in_period.count(),
                "dashboard_count": team_dashboards.count(),
                "dashboard_template_count": team_dashboards.filter(creation_mode="template").count(),
                "dashboard_shared_count": team_dashboards.filter(sharingconfiguration__enabled=True).count(),
                "dashboard_tagged_count": team_dashboards.exclude(tagged_items__isnull=True).count(),
                "ff_count": feature_flags.count(),
                "ff_active_count": feature_flags.filter(active=True).count(),
            }
            org_usage_summary["event_count_total"] += team_report["event_count_total"]
            org_usage_summary["event_count_new_in_period"] += team_report["event_count_new_in_period"]
            org_usage_summary["event_count_with_groups_new_in_period"] += team_report[
                "event_count_with_groups_new_in_period"
            ]
            org_usage_summary["recording_count_new_in_period"] += team_report["recording_count_new_in_period"]
            if team_report["group_types_total"] > 0:
                org_usage_summary["using_groups"] = True
            org_usage_summary["person_count_total"] += team_report["person_count_total"]
            org_usage_summary["person_count_new_in_period"] += team_report["person_count_new_in_period"]
            org_usage_summary["dashboard_count"] += team_report["dashboard_count"]
            org_usage_summary["ff_count"] += team_report["ff_count"]
            teams[team_id] = team_report
        except Exception as err:
            capture_event("get org usage report failure", organization_id, {"error": str(err)}, dry_run=dry_run)

    return {
        "org_usage_summary": org_usage_summary,
        "teams": teams,
    }


def get_instance_metadata(has_license: bool) -> OrgMetadata:
    period_start, period_end = get_previous_day()
    realm = get_instance_realm()
    metadata: OrgMetadata = {
        "posthog_version": VERSION,
        "deployment_infrastructure": os.getenv("DEPLOYMENT", "unknown"),
        "realm": realm,
        "period": {"start_inclusive": period_start.isoformat(), "end_inclusive": period_end.isoformat()},
        "site_url": os.getenv("SITE_URL", "unknown"),
        "product": get_product_name(realm, has_license),
    }

    if realm != "cloud":
        metadata["helm"] = get_helm_info_env()
        metadata["clickhouse_version"] = str(version_requirement.get_clickhouse_version())

        metadata["users_who_logged_in"] = [
            {"id": user.id, "distinct_id": user.distinct_id}
            if user.anonymize_data
            else {"id": user.id, "distinct_id": user.distinct_id, "first_name": user.first_name, "email": user.email}
            for user in User.objects.filter(is_active=True, last_login__gte=period_start)
        ]

        metadata["table_sizes"] = {
            "posthog_event": fetch_table_size("posthog_event"),
            "posthog_sessionrecordingevent": fetch_table_size("posthog_sessionrecordingevent"),
        }

        plugin_configs = PluginConfig.objects.select_related("plugin").all()

        metadata["plugins_installed"] = Counter(plugin_config.plugin.name for plugin_config in plugin_configs)
        metadata["plugins_enabled"] = Counter(
            plugin_config.plugin.name for plugin_config in plugin_configs if plugin_config.enabled
        )

    return metadata


def send_all_reports(*, dry_run: bool = False) -> List[OrgReport]:
    """
    Generic way to generate and send org usage reports.
    Specify Postgres or ClickHouse for event queries.
    """
    period_start, _ = get_previous_day()
    license = License.objects.first_valid()
    metadata = get_instance_metadata(bool(license))

    org_data: Dict[str, Dict[str, Any]] = {}
    org_reports: List[OrgReport] = []

    for team in Team.objects.exclude(organization__for_internal_metrics=True):
        org = team.organization
        organization_id = str(org.id)
        billing_service_token = None
        if license:
            billing_service_token = build_billing_token(license, organization_id)
        if organization_id in org_data:
            org_data[organization_id]["teams"].append(team.id)
        else:
            org_data[organization_id] = {
                "teams": [team.id],
                "user_count": get_org_user_count(organization_id),
                "name": org.name,
                "created_at": str(org.created_at),
                "token": billing_service_token,
            }

    for organization_id, org in org_data.items():
        org_owner = get_org_owner_or_first_user(organization_id)
        if not org_owner:
            continue
        distinct_id = org_owner.distinct_id
        usage = get_org_usage_report(organization_id, org["teams"], dry_run)
        try:
            report: OrgReport = {
                **metadata,  # type: ignore
                **usage,
                "admin_distinct_id": distinct_id,
                "organization_id": organization_id,
                "organization_name": org["name"],
                "organization_created_at": org["created_at"],
                "organization_user_count": org["user_count"],
                "team_count": len(org["teams"]),
                "date": period_start.strftime("%Y-%m-%d"),
            }
            org_reports.append(report)
            if not dry_run:
                send_report(report, org["token"])
                time.sleep(0.25)
        except Exception as err:
            capture_event("send org report failure", organization_id, {"error": str(err)}, dry_run=dry_run)

    return org_reports


def send_report(report: OrgReport, token: str):
    headers = {}
    if token:
        headers = {"Authorization": f"Bearer {token}"}
    request = requests.post(f"{BILLING_SERVICE_URL}/api/usage", json=report, headers=headers)
    if request.status_code != 200:
        raise Exception()


def get_product_name(realm: str, has_license: bool) -> str:
    if realm == "cloud":
        return "cloud"
    elif realm in {"hosted", "hosted-clickhouse"}:
        return "scale" if has_license else "open source"
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
            Exception("No user found for org while generating report"), {"org": {"organization_id": organization_id}}
        )
    return user


def capture_event(name: str, organization_id: str, report: Dict[str, Any], dry_run: bool) -> None:
    if not dry_run:
        posthoganalytics.api_key = "sTMFPsFhdP1Ssg"
        posthoganalytics.capture(
            get_machine_id(),
            name,
            {**report, "scope": "machine"},
            groups={"organization": organization_id, "instance": settings.SITE_URL},
        )

        if is_cloud():
            posthoganalytics.group_identify("organization", organization_id, report)
        else:
            posthoganalytics.group_identify("instance", settings.SITE_URL, report)

        for user in User.objects.all():
            posthoganalytics.capture(user.distinct_id, f"user {name}", {**report, "scope": "user"})
    else:
        print(name, json.dumps(report))  # noqa: T201


def fetch_instance_params(report: Dict[str, Any]) -> dict:
    return {
        "site_url": settings.SITE_URL,
        "machine_id": get_machine_id(),
        "posthog_version": report["posthog_version"],
        "deployment": report["deployment"],
        "realm": report["realm"],
        **report["org_usage_summary"],
    }


def fetch_table_size(table_name: str) -> int:
    return fetch_sql("SELECT pg_total_relation_size(%s) as size", (table_name,))[0].size


def fetch_sql(sql_: str, params: Tuple[Any, ...]) -> List[Any]:
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL(sql_), params)
        return namedtuplefetchall(cursor)
