import dataclasses
import os
from collections import Counter
from datetime import datetime
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    TypedDict,
    Union,
    cast,
)

import dateutil
import requests
import structlog
from django.conf import settings
from django.db import connection
from django.db.models import Count, Q
from posthoganalytics.client import Client
from psycopg2 import sql
from sentry_sdk import capture_exception

from ee.api.billing import BillingManager
from posthog import version_requirement
from posthog.celery import app
from posthog.client import sync_execute
from posthog.cloud_utils import is_cloud
from posthog.models import GroupTypeMapping, OrganizationMembership, User
from posthog.models.dashboard import Dashboard
from posthog.models.feature_flag import FeatureFlag
from posthog.models.organization import Organization
from posthog.models.plugin import PluginConfig
from posthog.models.team.team import Team
from posthog.models.utils import namedtuplefetchall
from posthog.settings import INSTANCE_TAG
from posthog.utils import get_helm_info_env, get_instance_realm, get_machine_id, get_previous_day
from posthog.version import VERSION

logger = structlog.get_logger(__name__)

Period = TypedDict("Period", {"start_inclusive": str, "end_inclusive": str})
TableSizes = TypedDict("TableSizes", {"posthog_event": int, "posthog_sessionrecordingevent": int})


@dataclasses.dataclass
class UsageReportCounters:
    event_count_lifetime: int
    event_count_in_period: int
    event_count_in_month: int
    event_count_with_groups_in_period: int
    # event_count_by_lib: Dict
    # event_count_by_name: Dict
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


# Instance metadata to be included in oveall report
@dataclasses.dataclass
class InstanceMetadata:
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
    instance_tag: str


@dataclasses.dataclass
class OrgReport(UsageReportCounters):
    date: str
    organization_id: str
    organization_name: str
    organization_created_at: str
    organization_user_count: int
    team_count: int
    teams: Dict[int, UsageReportCounters]


@dataclasses.dataclass
class FullUsageReport(OrgReport, InstanceMetadata):
    pass


def fetch_table_size(table_name: str) -> int:
    return fetch_sql("SELECT pg_total_relation_size(%s) as size", (table_name,))[0].size


def fetch_sql(sql_: str, params: Tuple[Any, ...]) -> List[Any]:
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL(sql_), params)
        return namedtuplefetchall(cursor)


def get_product_name(realm: str, has_license: bool) -> str:
    if realm == "cloud":
        return "cloud"
    elif realm in {"hosted", "hosted-clickhouse"}:
        return "scale" if has_license else "open source"
    else:
        return "unknown"


def get_instance_metadata(period: Tuple[datetime, datetime]) -> InstanceMetadata:
    has_license = False

    if settings.EE_AVAILABLE:
        from ee.models.license import License

        license = License.objects.first_valid()
        has_license = license is not None

    period_start, period_end = period

    realm = get_instance_realm()
    metadata = InstanceMetadata(
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
        instance_tag=INSTANCE_TAG,
    )

    if realm != "cloud":
        metadata.helm = get_helm_info_env()
        metadata.clickhouse_version = str(version_requirement.get_clickhouse_version())

        metadata.users_who_logged_in = [
            {"id": user.id, "distinct_id": user.distinct_id}
            if user.anonymize_data
            else {"id": user.id, "distinct_id": user.distinct_id, "first_name": user.first_name, "email": user.email}
            for user in User.objects.filter(is_active=True, last_login__gte=period_start, last_login__lte=period_end)
        ]
        metadata.users_who_logged_in_count = len(metadata.users_who_logged_in)

        metadata.users_who_signed_up = [
            {"id": user.id, "distinct_id": user.distinct_id}
            if user.anonymize_data
            else {"id": user.id, "distinct_id": user.distinct_id, "first_name": user.first_name, "email": user.email}
            for user in User.objects.filter(is_active=True, date_joined__gte=period_start, date_joined__lte=period_end)
        ]
        metadata.users_who_signed_up_count = len(metadata.users_who_signed_up)

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


def get_org_user_count(organization_id: str) -> int:
    return OrganizationMembership.objects.filter(organization_id=organization_id).count()


def get_org_owner_or_first_user(organization_id: str) -> Optional[User]:
    # Find the membership object for the org owner
    user = None
    membership = OrganizationMembership.objects.filter(
        organization_id=organization_id, level=OrganizationMembership.Level.OWNER
    ).first()
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


def send_report_to_billing_service(organization: Organization, report: Dict) -> None:
    if not settings.EE_AVAILABLE:
        return

    from ee.api.billing import build_billing_token
    from ee.models.license import License
    from ee.settings import BILLING_SERVICE_URL

    license = License.objects.first_valid()
    if not license or not license.is_v2_license:
        return

    token = build_billing_token(license, organization)

    headers = {}
    if token:
        headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(f"{BILLING_SERVICE_URL}/api/usage", json=report, headers=headers)
    if response.status_code != 200:
        raise Exception(
            f"Failed to send usage report to billing service code:{response.status_code} response:{response.text}"
        )

    response_data: Dict[str, Any] = response.json()
    BillingManager(license)._update_org_details(organization, response_data)


def capture_event(
    pha_client: Client,
    name: str,
    organization_id: str,
    properties: Dict[str, Any],
    timestamp: Optional[datetime] = None,
) -> None:
    if is_cloud():
        org_owner = get_org_owner_or_first_user(organization_id)
        distinct_id = org_owner.distinct_id if org_owner and org_owner.distinct_id else f"org-{organization_id}"
        pha_client.capture(
            distinct_id,
            name,
            {**properties, "scope": "user"},
            groups={"organization": organization_id, "instance": settings.SITE_URL},
            timestamp=timestamp,
        )
        pha_client.group_identify("organization", organization_id, properties)
    else:
        pha_client.capture(
            get_machine_id(),
            name,
            {**properties, "scope": "machine"},
            groups={"instance": settings.SITE_URL},
            timestamp=timestamp,
        )
        pha_client.group_identify("instance", settings.SITE_URL, properties)


def get_teams_with_event_count_lifetime() -> List[Tuple[int, int]]:
    result = sync_execute(
        """
        SELECT team_id, count(1) as count
        FROM events
        GROUP BY team_id
    """
    )
    return result


def get_teams_with_event_count_in_period(begin: datetime, end: datetime) -> List[Tuple[int, int]]:
    result = sync_execute(
        """
        SELECT team_id, count(1) as count
        FROM events
        WHERE timestamp between %(begin)s AND %(end)s
        GROUP BY team_id
    """,
        {"begin": begin, "end": end},
    )
    return result


def get_teams_with_event_count_with_groups_in_period(begin: datetime, end: datetime) -> List[Tuple[int, int]]:
    result = sync_execute(
        """
        SELECT team_id, count(1) as count
        FROM events
        WHERE timestamp between %(begin)s AND %(end)s
        AND ($group_0 != '' OR $group_1 != '' OR $group_2 != '' OR $group_3 != '' OR $group_4 != '')
        GROUP BY team_id
    """,
        {"begin": begin, "end": end},
    )
    return result


def get_teams_with_event_count_by_lib(begin: datetime, end: datetime) -> List[Tuple[int, str, int]]:
    results = sync_execute(
        """
        SELECT team_id, JSONExtractString(properties, '$lib') as lib, COUNT(1) as count
        FROM events
        WHERE timestamp between %(begin)s AND %(end)s
        GROUP BY lib, team_id
    """,
        {"begin": begin, "end": end},
    )
    return results


def get_teams_with_event_count_by_name(begin: datetime, end: datetime) -> List[Tuple[int, str, int]]:
    results = sync_execute(
        """
        SELECT team_id, event, COUNT(1) as count
        FROM events
        WHERE timestamp between %(begin)s AND %(end)s
        GROUP BY event, team_id
    """,
        {"begin": begin, "end": end},
    )
    return results


def get_teams_with_recording_count_in_period(begin: datetime, end: datetime) -> List[Tuple[int, int]]:
    result = sync_execute(
        """
        SELECT team_id, count(distinct session_id) as count
        FROM session_recording_events
        WHERE timestamp between %(begin)s AND %(end)s
        GROUP BY team_id
    """,
        {"begin": begin, "end": end},
    )
    return result


def get_teams_with_recording_count_total() -> List[Tuple[int, int]]:
    result = sync_execute(
        """
        SELECT team_id, count(distinct session_id) as count
        FROM session_recording_events
        GROUP BY team_id
    """
    )
    return result


def find_count_for_team_in_rows(team_id: int, rows: list) -> int:
    for row in rows:
        if "team_id" in row:
            if row["team_id"] == team_id:
                return row["total"]
        elif row[0] == team_id:
            return row[1]
    return 0


@app.task(ignore_result=True, retries=3)
def send_all_org_usage_reports(
    dry_run: bool = False,
    at: Optional[str] = None,
    capture_event_name: Optional[str] = None,
    skip_capture_event: bool = False,
    only_organization_id: Optional[str] = None,
) -> List[dict]:  # Dict[str, OrgReport]:
    pha_client = Client("sTMFPsFhdP1Ssg")
    capture_event_name = capture_event_name or "organization usage report"

    at_date = dateutil.parser.parse(at) if at else None
    period = get_previous_day(at=at_date)
    period_start, period_end = period

    instance_metadata = get_instance_metadata(period)

    # Clickhouse is good at counting things so we count across all teams rather than doing it one by one
    all_data = dict(
        teams_with_event_count_lifetime=get_teams_with_event_count_lifetime(),
        teams_with_event_count_in_period=get_teams_with_event_count_in_period(period_start, period_end),
        teams_with_event_count_in_month=get_teams_with_event_count_in_period(period_start.replace(day=1), period_end),
        teams_with_event_count_with_groups_in_period=get_teams_with_event_count_with_groups_in_period(
            period_start, period_end
        ),
        # teams_with_event_count_by_lib=get_teams_with_event_count_by_lib(period_start, period_end),
        # teams_with_event_count_by_name=get_teams_with_event_count_by_name(period_start, period_end),
        teams_with_recording_count_in_period=get_teams_with_recording_count_in_period(period_start, period_end),
        teams_with_recording_count_total=get_teams_with_recording_count_total(),
        teams_with_group_types_total=list(
            GroupTypeMapping.objects.values("team_id").annotate(total=Count("id")).order_by("team_id")
        ),
        teams_with_dashboard_count=list(
            Dashboard.objects.values("team_id").annotate(total=Count("id")).order_by("team_id")
        ),
        teams_with_dashboard_template_count=list(
            Dashboard.objects.filter(creation_mode="template")
            .values("team_id")
            .annotate(total=Count("id"))
            .order_by("team_id")
        ),
        teams_with_dashboard_shared_count=list(
            Dashboard.objects.filter(sharingconfiguration__enabled=True)
            .values("team_id")
            .annotate(total=Count("id"))
            .order_by("team_id")
        ),
        teams_with_dashboard_tagged_count=list(
            Dashboard.objects.filter(tagged_items__isnull=False)
            .values("team_id")
            .annotate(total=Count("id"))
            .order_by("team_id")
        ),
        teams_with_ff_count=list(FeatureFlag.objects.values("team_id").annotate(total=Count("id")).order_by("team_id")),
        teams_with_ff_active_count=list(
            FeatureFlag.objects.filter(active=True).values("team_id").annotate(total=Count("id")).order_by("team_id")
        ),
    )

    teams: Sequence[Team] = list(
        Team.objects.select_related("organization").exclude(
            Q(organization__for_internal_metrics=True) | Q(is_demo=True)
        )
    )

    org_reports: Dict[str, OrgReport] = {}
    orgs_by_id: Dict[str, Organization] = {}

    for team in teams:
        team_report = UsageReportCounters(
            event_count_lifetime=find_count_for_team_in_rows(team.id, all_data["teams_with_event_count_lifetime"]),
            event_count_in_period=find_count_for_team_in_rows(team.id, all_data["teams_with_event_count_in_period"]),
            event_count_in_month=find_count_for_team_in_rows(team.id, all_data["teams_with_event_count_in_month"]),
            event_count_with_groups_in_period=find_count_for_team_in_rows(
                team.id, all_data["teams_with_event_count_with_groups_in_period"]
            ),
            # event_count_by_lib: Difind_count_for_team_in_rows(team.id, all_data["teams_with_#"]),
            # event_count_by_name: Difind_count_for_team_in_rows(team.id, all_data["teams_with_#"]),
            recording_count_in_period=find_count_for_team_in_rows(
                team.id, all_data["teams_with_recording_count_in_period"]
            ),
            recording_count_total=find_count_for_team_in_rows(team.id, all_data["teams_with_recording_count_total"]),
            group_types_total=find_count_for_team_in_rows(team.id, all_data["teams_with_group_types_total"]),
            dashboard_count=find_count_for_team_in_rows(team.id, all_data["teams_with_dashboard_count"]),
            dashboard_template_count=find_count_for_team_in_rows(
                team.id, all_data["teams_with_dashboard_template_count"]
            ),
            dashboard_shared_count=find_count_for_team_in_rows(team.id, all_data["teams_with_dashboard_shared_count"]),
            dashboard_tagged_count=find_count_for_team_in_rows(team.id, all_data["teams_with_dashboard_tagged_count"]),
            ff_count=find_count_for_team_in_rows(team.id, all_data["teams_with_ff_count"]),
            ff_active_count=find_count_for_team_in_rows(team.id, all_data["teams_with_ff_active_count"]),
        )

        org_id = str(team.organization.id)

        if org_id not in org_reports:
            orgs_by_id[org_id] = team.organization

            org_report = OrgReport(
                date=period_start.strftime("%Y-%m-%d"),
                organization_id=org_id,
                organization_name=team.organization.name,
                organization_created_at=team.organization.created_at.isoformat(),
                organization_user_count=get_org_user_count(org_id),
                team_count=1,
                teams={team.id: team_report},
                **dataclasses.asdict(team_report),  # Clone the team report as the basis
            )
            org_reports[org_id] = org_report
        else:
            org_report = org_reports[org_id]
            org_report.teams[team.id] = team_report
            org_report.team_count += 1

            # Iterate on all fields of the UsageReportCounters and add the values from the team report to the org report
            for field in dataclasses.fields(UsageReportCounters):
                if hasattr(team_report, field.name):
                    setattr(
                        org_report,
                        field.name,
                        getattr(org_report, field.name) + getattr(team_report, field.name),
                    )

    all_reports = []

    for org_report in org_reports.values():
        org_id = org_report.organization_id

        if only_organization_id and only_organization_id != org_id:
            continue

        full_report = FullUsageReport(
            **dataclasses.asdict(org_report),
            **dataclasses.asdict(instance_metadata),
        )
        full_report_dict = dataclasses.asdict(full_report)
        all_reports.append(full_report_dict)

        if dry_run:
            continue

        # First capture the events to PostHog
        try:
            if not skip_capture_event:
                capture_event(pha_client, capture_event_name, org_id, full_report_dict, timestamp=at_date)
            logger.info(f"UsageReport sent to PostHog for organization {org_id}")
        except Exception as err:
            logger.error(
                f"UsageReport sent to PostHog for organization {org_id} failed: {str(err)}",
            )
            if not skip_capture_event:
                capture_exception(err)
            capture_event(pha_client, f"{capture_event_name} failure", org_id, {"error": str(err)})

        # Then capture the events to Billing
        try:
            send_report_to_billing_service(orgs_by_id[org_id], full_report_dict)
            logger.info(f"UsageReport sent to Billing for organization {org_id}")
        except Exception as err:
            logger.error(f"UsageReport failed sending to Billing for organization {org_id}: {err}")
            capture_exception(err)
            capture_event(pha_client, f"{capture_event_name} to billing service failure", org_id, {"err": str(err)})

    pha_client.flush()

    return all_reports
