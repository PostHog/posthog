import dataclasses
import os
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

import dateutil
import requests
import structlog
from celery import group
from django.conf import settings
from django.db import connection
from django.db.models.manager import BaseManager
from posthoganalytics.client import Client
from psycopg2 import sql
from sentry_sdk import capture_exception

from posthog import version_requirement
from posthog.celery import app
from posthog.cloud_utils import is_cloud
from posthog.models import GroupTypeMapping, OrganizationMembership, User
from posthog.models.dashboard import Dashboard
from posthog.models.event.util import (
    get_agg_event_count_for_teams_and_period,
    get_event_count_for_team,
    get_event_count_for_team_and_period,
    get_event_count_with_groups_count_for_team_and_period,
    get_events_count_for_team_by_client_lib,
    get_events_count_for_team_by_event_type,
)
from posthog.models.feature_flag import FeatureFlag
from posthog.models.organization import Organization
from posthog.models.plugin import PluginConfig
from posthog.models.session_recording_event.util import (
    get_agg_recording_count_for_teams_and_period,
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
    event_count_in_month: int
    event_count_with_groups_in_period: int
    event_count_by_lib: Dict
    event_count_by_name: Dict
    # Recordings
    recording_count_in_period: int
    recording_count_total: int
    # Persons and Groups
    group_types_total: int
    # person_count_total: int
    # person_count_in_period: int
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
    # person_count_in_period: int
    # person_count_total: int
    using_groups: bool
    group_types_total: int
    # Dashboards
    dashboard_count: int
    # Feature flags
    ff_count: int
    ff_active_count: int
    teams: Dict[int, TeamUsageReport]


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


def get_org_usage_report(period: Tuple[datetime, datetime], team_ids: List[int]) -> OrgUsageSummary:
    period_start, period_end = period

    org_usage_summary = OrgUsageSummary(
        event_count_lifetime=0,
        event_count_in_period=0,
        event_count_in_month=0,
        event_count_with_groups_in_period=0,
        event_count_with_groups_in_month=0,
        recording_count_in_period=0,
        recording_count_total=0,
        # person_count_in_period=0,
        # person_count_total=0,
        using_groups=False,
        group_types_total=0,
        dashboard_count=0,
        ff_count=0,
        ff_active_count=0,
        teams={},
    )

    for team_id in team_ids:
        # Dashboards
        team_dashboards = Dashboard.objects.filter(team_id=team_id).exclude(deleted=True)

        # Feature Flags
        feature_flags = FeatureFlag.objects.filter(team_id=team_id).exclude(deleted=True)

        team_report = TeamUsageReport(
            event_count_lifetime=get_event_count_for_team(team_id),
            event_count_in_period=get_event_count_for_team_and_period(team_id, period_start, period_end),
            event_count_in_month=get_event_count_for_team_and_period(team_id, period_start.replace(day=1), period_end),
            event_count_with_groups_in_period=get_event_count_with_groups_count_for_team_and_period(
                team_id, period_start, period_end
            ),
            event_count_by_lib=get_events_count_for_team_by_client_lib(team_id, period_start, period_end),
            event_count_by_name=get_events_count_for_team_by_event_type(team_id, period_start, period_end),
            recording_count_in_period=get_recording_count_for_team_and_period(team_id, period_start, period_end),
            recording_count_total=get_recording_count_for_team(team_id),
            group_types_total=GroupTypeMapping.objects.filter(team_id=team_id).count(),
            # NOTE: Below is disabled until we figure out a CH query - Postgres count is far too slow
            # person_count_total=get_person_count_for_team(team_id),
            # person_count_in_period=get_person_count_for_team_and_period(team_id, period_start, period_end),
            dashboard_count=team_dashboards.count(),
            dashboard_template_count=team_dashboards.filter(creation_mode="template").count(),
            dashboard_shared_count=team_dashboards.filter(sharingconfiguration__enabled=True).count(),
            dashboard_tagged_count=team_dashboards.exclude(tagged_items__isnull=True).count(),
            ff_count=feature_flags.count(),
            ff_active_count=feature_flags.filter(active=True).count(),
        )

        # Iterate on all fields of the OrgusageSummary and add the values from the team report
        for field in dataclasses.fields(OrgUsageSummary):
            if hasattr(team_report, field.name):
                setattr(
                    org_usage_summary,
                    field.name,
                    getattr(org_usage_summary, field.name) + getattr(team_report, field.name),
                )

        if team_report.group_types_total > 0:
            org_usage_summary.using_groups = True

        org_usage_summary.teams[team_id] = team_report

    return org_usage_summary


def get_instance_metadata(period: Tuple[datetime, datetime]) -> OrgMetadata:
    has_license = False

    if settings.EE_AVAILABLE:
        from ee.models.license import License

        license = License.objects.first_valid()
        has_license = license is not None

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


def send_report_to_billing_service(organization: Organization, report: Dict) -> None:
    if not settings.EE_AVAILABLE:
        return

    from ee.api.billing import build_billing_token
    from ee.models.license import License
    from ee.settings import BILLING_SERVICE_URL

    license = License.objects.first_valid()
    token = build_billing_token(license, organization) if license else None

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


@app.task(autoretry_for=(Exception,), max_retries=3, retry_backoff=True, acks_late=True)
def send_org_usage_report(
    organization_id: Optional[str] = None, dry_run: bool = False, at: Optional[str] = None
) -> Dict:
    at_date = dateutil.parser.parse(at) if at else None
    period = get_previous_day(at=at_date)
    period_start, period_end = period

    metadata = get_instance_metadata(period)
    organization = Organization.objects.get(id=organization_id)
    organization_id = str(organization.id)
    teams = organization.teams.all()
    team_ids: List[int] = [team.id for team in teams]

    try:
        org_owner = get_org_owner_or_first_user(organization_id)

        if not org_owner:
            raise Exception("No owner found for organization")

        logger.info("Sending usage report for organization %s ...", organization_id)

        distinct_id = org_owner.distinct_id
        usage = get_org_usage_report(period, team_ids)

        report = OrgReport(
            admin_distinct_id=distinct_id,
            organization_id=organization_id,
            organization_name=organization.name,
            organization_created_at=organization.created_at.isoformat(),
            organization_user_count=get_org_user_count(organization_id),
            team_count=len(team_ids),
            date=period_start.strftime("%Y-%m-%d"),
        )

        full_report = OrgReportFull(
            **dataclasses.asdict(report),
            **dataclasses.asdict(metadata),
            **dataclasses.asdict(usage),
        )
        full_report_dict = dataclasses.asdict(full_report)

        if not dry_run:
            capture_event("organization usage report", organization_id, full_report_dict, timestamp=at_date)
            send_report_to_billing_service(organization, full_report_dict)

        logger.info("Usage report for organization %s sent!", organization_id)

        return full_report_dict

    except Exception as err:
        logger.error("Usage report for organization %s failed!", organization_id)
        if not dry_run:
            # If we except we still want to capture the minimum amount of info for the Billing Service
            minimal_report_dict = {
                "organization_id": organization_id,
                "date": period_start.strftime("%Y-%m-%d"),
                "event_count_in_period": get_agg_event_count_for_teams_and_period(team_ids, period_start, period_end),
                "recording_count_in_period": get_agg_recording_count_for_teams_and_period(
                    team_ids, period_start, period_end
                ),
            }
            send_report_to_billing_service(organization, minimal_report_dict)
            capture_exception(err)
            capture_event("organization usage report failure", organization_id, {"error": str(err)})

        raise err


@app.task(ignore_result=True)
def send_all_org_usage_reports(dry_run: bool = False, at: Optional[str] = None) -> Any:

    all_orgs = Organization.objects.exclude(for_internal_metrics=True).values("id")
    tasks = [send_org_usage_report.s(org["id"], dry_run=dry_run, at=at) for org in all_orgs]

    return group(tasks).apply_async()
