import dataclasses
import os
import time
from collections import Counter
from datetime import datetime
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

import requests
import structlog
from django.conf import settings
from django.db import connection
from django.db.models.manager import BaseManager
from posthoganalytics.client import Client
from psycopg2 import sql
from sentry_sdk import capture_exception

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
from posthog.models.session_recording_event.util import (
    get_recording_count_for_team,
    get_recording_count_for_team_and_period,
)
from posthog.models.utils import namedtuplefetchall
from posthog.utils import get_helm_info_env, get_instance_realm, get_machine_id, get_previous_day
from posthog.version import VERSION

logger = structlog.get_logger(__name__)

Period = TypedDict("Period", {"start_inclusive": str, "end_inclusive": str})
TableSizes = TypedDict("TableSizes", {"posthog_event": int, "posthog_sessionrecordingevent": int})


@dataclasses.dataclass
class TeamUsageReport:
    event_count_lifetime: int
    event_count_in_period: int
    event_count_with_groups_in_period: int
    event_count_by_lib: Dict
    event_count_by_name: Dict
    # Recordings
    recording_count_in_period: int
    recording_count_total: int
    duplicate_distinct_ids: Dict
    multiple_ids_per_person: Dict
    # Persons and Groups
    group_types_total: int
    person_count_total: int
    person_count_in_period: int
    # Dashboards
    dashboard_count: int
    dashboard_template_count: int
    dashboard_shared_count: int
    dashboard_tagged_count: int
    # Feature flags
    ff_count: int
    ff_active_count: int


@dataclasses.dataclass
class OrgUsageSummary:
    # Events
    event_count_lifetime: int
    event_count_in_period: int
    event_count_in_month: int
    event_count_with_groups_in_period: int
    event_count_with_groups_in_month: int
    # Recordins
    recording_count_in_period: int
    recording_count_total: int
    # Persons and groups
    person_count_in_period: int
    person_count_total: int
    using_groups: bool
    group_types_total: int
    # Dashboards
    dashboard_count: int
    # Feature flags
    ff_count: int
    ff_active_count: int
    teams: Dict[str, TeamUsageReport]


@dataclasses.dataclass
class OrgMetadata:
    posthog_version: str
    deployment_infrastructure: str
    realm: str
    period: Period
    site_url: str
    product: str
    helm: Optional[dict]
    clickhouse_version: Optional[str]
    users_who_logged_in: Optional[List[Dict[str, Union[str, int]]]]
    users_who_logged_in_count: Optional[int]
    users_who_signed_up: Optional[List[Dict[str, Union[str, int]]]]
    users_who_signed_up_count: Optional[int]
    table_sizes: Optional[TableSizes]
    plugins_installed: Optional[Dict]
    plugins_enabled: Optional[Dict]


@dataclasses.dataclass
class OrgReport:
    date: str
    admin_distinct_id: int
    organization_id: str
    organization_name: str
    organization_created_at: str
    organization_user_count: int
    team_count: int


@dataclasses.dataclass
class OrgReportFull(OrgReport, OrgMetadata, OrgUsageSummary):
    pass


def get_org_usage_report(period: Tuple[datetime, datetime], team_ids: List[str]) -> OrgUsageSummary:
    period_start, period_end = period

    org_usage_summary = OrgUsageSummary(
        event_count_lifetime=0,
        event_count_in_period=0,
        event_count_in_month=0,
        event_count_with_groups_in_period=0,
        event_count_with_groups_in_month=0,
        recording_count_in_period=0,
        recording_count_total=0,
        person_count_in_period=0,
        person_count_total=0,
        using_groups=False,
        group_types_total=0,
        dashboard_count=0,
        ff_count=0,
        ff_active_count=0,
        teams={},
    )

    for team_id in team_ids:
        # pull person stats and the rest here from Postgres always
        persons_considered_total = Person.objects.filter(team_id=team_id)
        persons_considered_total_new_in_period = persons_considered_total.filter(
            created_at__gte=period_start, created_at__lte=period_end
        )

        # Dashboards
        team_dashboards = Dashboard.objects.filter(team_id=team_id).exclude(deleted=True)

        # Feature Flags
        feature_flags = FeatureFlag.objects.filter(team_id=team_id).exclude(deleted=True)

        team_report = TeamUsageReport(
            event_count_lifetime=get_event_count_for_team(team_id),
            event_count_in_period=get_event_count_for_team_and_period(team_id, period_start, period_end),
            event_count_with_groups_in_period=get_event_count_with_groups_count_for_team_and_period(
                team_id, period_start, period_end
            ),
            event_count_by_lib=get_events_count_for_team_by_client_lib(team_id, period_start, period_end),
            event_count_by_name=get_events_count_for_team_by_event_type(team_id, period_start, period_end),
            recording_count_in_period=get_recording_count_for_team_and_period(team_id, period_start, period_end),
            recording_count_total=get_recording_count_for_team(team_id),
            duplicate_distinct_ids=count_duplicate_distinct_ids_for_team(team_id),
            multiple_ids_per_person=count_total_persons_with_multiple_ids(team_id),
            group_types_total=GroupTypeMapping.objects.filter(team_id=team_id).count(),
            person_count_total=persons_considered_total.count(),
            person_count_in_period=persons_considered_total_new_in_period.count(),
            dashboard_count=team_dashboards.count(),
            dashboard_template_count=team_dashboards.filter(creation_mode="template").count(),
            dashboard_shared_count=team_dashboards.filter(sharingconfiguration__enabled=True).count(),
            dashboard_tagged_count=team_dashboards.exclude(tagged_items__isnull=True).count(),
            ff_count=feature_flags.count(),
            ff_active_count=feature_flags.filter(active=True).count(),
        )

        org_usage_summary.event_count_lifetime += team_report.event_count_lifetime
        org_usage_summary.event_count_in_period += team_report.event_count_in_period
        org_usage_summary.event_count_with_groups_in_period += team_report.event_count_with_groups_in_period
        org_usage_summary.recording_count_in_period += team_report.recording_count_in_period
        org_usage_summary.group_types_total += team_report.group_types_total
        if team_report.group_types_total > 0:
            org_usage_summary.using_groups = True

        org_usage_summary.person_count_total += team_report.person_count_total
        org_usage_summary.person_count_in_period += team_report.person_count_in_period
        org_usage_summary.dashboard_count += team_report.dashboard_count
        org_usage_summary.ff_count += team_report.ff_count

        org_usage_summary.teams[team_id] = team_report

    return org_usage_summary


def get_instance_metadata(period: Tuple[datetime, datetime], has_license: bool) -> OrgMetadata:
    period_start, period_end = period

    realm = get_instance_realm()
    metadata = OrgMetadata(
        posthog_version=VERSION,
        deployment_infrastructure=os.getenv("DEPLOYMENT", "unknown"),
        realm=realm,
        period={"start_inclusive": period_start.isoformat(), "end_inclusive": period_end.isoformat()},
        site_url=settings.SITE_URL,
        product=get_product_name(realm, has_license),
        # Non-cloud vars
        helm=None,
        clickhouse_version=None,
        users_who_logged_in=None,
        users_who_logged_in_count=None,
        users_who_signed_up=None,
        users_who_signed_up_count=None,
        table_sizes=None,
        plugins_installed=None,
        plugins_enabled=None,
    )

    if realm != "cloud":
        metadata.helm = get_helm_info_env()
        metadata.clickhouse_version = str(version_requirement.get_clickhouse_version())

        metadata.users_who_logged_in = [
            {"id": user.id, "distinct_id": user.distinct_id}
            if user.anonymize_data
            else {"id": user.id, "distinct_id": user.distinct_id, "first_name": user.first_name, "email": user.email}
            for user in User.objects.filter(is_active=True, last_login__gte=period_start)
        ]

        metadata.table_sizes = {
            "posthog_event": fetch_table_size("posthog_event"),
            "posthog_sessionrecordingevent": fetch_table_size("posthog_sessionrecordingevent"),
        }

        plugin_configs = PluginConfig.objects.select_related("plugin").all()

        metadata.plugins_installed = dict(Counter(plugin_config.plugin.name for plugin_config in plugin_configs))
        metadata.plugins_enabled = dict(
            Counter(plugin_config.plugin.name for plugin_config in plugin_configs if plugin_config.enabled)
        )

    return metadata


def send_all_org_usage_reports(
    dry_run: bool = False, at: Optional[datetime] = None, only_organization_id: Optional[str] = None
) -> List[Dict]:
    """
    Generic way to generate and send org usage reports.
    Specify Postgres or ClickHouse for event queries.
    """
    period = get_previous_day(at=at)
    period_start, _ = period

    license = License.objects.first_valid()
    metadata = get_instance_metadata(period, bool(license))

    org_data: Dict[str, Dict[str, Any]] = {}
    org_reports: List[Dict] = []

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
        # NOTE: We should consider scheduling this rather than immediately invoking, that way we can have retries per org
        if only_organization_id and organization_id != only_organization_id:
            continue
        try:
            org_owner = get_org_owner_or_first_user(organization_id)
            if not org_owner:
                continue
            distinct_id = org_owner.distinct_id
            usage = get_org_usage_report(period, org["teams"])

            report = OrgReport(
                admin_distinct_id=distinct_id,
                organization_id=organization_id,
                organization_name=org["name"],
                organization_created_at=org["created_at"],
                organization_user_count=org["user_count"],
                team_count=len(org["teams"]),
                date=period_start.strftime("%Y-%m-%d"),
            )

            full_report = OrgReportFull(
                **dataclasses.asdict(report),
                **dataclasses.asdict(metadata),
                **dataclasses.asdict(usage),
            )
            full_report_dict = dataclasses.asdict(full_report)

            org_reports.append(full_report_dict)
            if not dry_run:
                capture_event("organization usage report", organization_id, full_report_dict, timestamp=at)
                send_report(full_report_dict, org["token"])
                time.sleep(0.25)
        except Exception as err:
            if dry_run:
                raise err
            else:
                capture_exception(err)
                capture_event("organization usage report failure", organization_id, {"error": str(err)})

    return org_reports


def send_report(report: Dict, token: str):
    headers = {}
    if token:
        headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(f"{BILLING_SERVICE_URL}/api/usage", json=report, headers=headers)
    if response.status_code != 200:
        capture_event("billing service usage report failure", report["organization_id"], {"code": response.status_code})


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


def capture_event(
    name: str, organization_id: str, properties: Dict[str, Any], timestamp: Optional[datetime] = None
) -> None:
    phcloud_client = Client("sTMFPsFhdP1Ssg")
    if is_cloud():
        org_owner = get_org_owner_or_first_user(organization_id)
        phcloud_client.capture(
            org_owner.distinct_id,  # type: ignore
            name,
            {**properties, "scope": "user"},
            groups={"organization": organization_id, "instance": settings.SITE_URL},
            timestamp=timestamp,
        )
        phcloud_client.group_identify("organization", organization_id, properties)
    else:
        phcloud_client.capture(
            get_machine_id(),
            name,
            {**properties, "scope": "machine"},
            groups={"instance": settings.SITE_URL},
            timestamp=timestamp,
        )
        phcloud_client.group_identify("instance", settings.SITE_URL, properties)

    phcloud_client.flush()


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
