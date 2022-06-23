import json
import os
from collections import Counter
from typing import Any, Dict, List, Tuple

import posthoganalytics
import structlog
from django.conf import settings
from django.db import connection
from psycopg2 import sql

from posthog import version_requirement
from posthog.models import GroupTypeMapping, Person, Team, User
from posthog.models.dashboard import Dashboard
from posthog.models.event.util import (
    get_event_count_for_team,
    get_event_count_for_team_and_period,
    get_events_count_for_team_by_client_lib,
    get_events_count_for_team_by_event_type,
)
from posthog.models.feature_flag import FeatureFlag
from posthog.models.person.util import count_duplicate_distinct_ids_for_team, count_total_persons_with_multiple_ids
from posthog.models.plugin import PluginConfig
from posthog.models.utils import namedtuplefetchall
from posthog.utils import get_helm_info_env, get_instance_realm, get_machine_id, get_previous_week
from posthog.version import VERSION

logger = structlog.get_logger(__name__)


def status_report(*, dry_run: bool = False) -> Dict[str, Any]:
    period_start, period_end = get_previous_week()
    report: Dict[str, Any] = {
        "posthog_version": VERSION,
        "clickhouse_version": str(version_requirement.get_clickhouse_version()),
        "deployment": os.getenv("DEPLOYMENT", "unknown"),
        "realm": get_instance_realm(),
        "period": {"start_inclusive": period_start.isoformat(), "end_inclusive": period_end.isoformat()},
        "site_url": os.getenv("SITE_URL", "unknown"),
        "license_keys": get_instance_licenses(),
    }

    report["helm"] = get_helm_info_env()

    report["users_who_logged_in"] = [
        {"id": user.id, "distinct_id": user.distinct_id}
        if user.anonymize_data
        else {"id": user.id, "distinct_id": user.distinct_id, "first_name": user.first_name, "email": user.email}
        for user in User.objects.filter(is_active=True, last_login__gte=period_start)
    ]
    report["teams"] = {}
    report["table_sizes"] = {
        "posthog_event": fetch_table_size("posthog_event"),
        "posthog_sessionrecordingevent": fetch_table_size("posthog_sessionrecordingevent"),
    }

    plugin_configs = PluginConfig.objects.select_related("plugin").all()

    report["plugins_installed"] = Counter(plugin_config.plugin.name for plugin_config in plugin_configs)
    report["plugins_enabled"] = Counter(
        plugin_config.plugin.name for plugin_config in plugin_configs if plugin_config.enabled
    )

    instance_usage_summary: Dict[str, int] = {
        "events_count_new_in_period": 0,
        "persons_count_new_in_period": 0,
        "persons_count_total": 0,
        "events_count_total": 0,
        "dashboards_count": 0,
        "ff_count": 0,
        "using_groups": False,
    }

    for team in Team.objects.exclude(organization__for_internal_metrics=True):
        try:
            params = (team.id, report["period"]["start_inclusive"], report["period"]["end_inclusive"])
            team_report: Dict[str, Any] = {}
            # pull events stats from clickhouse

            team_event_count = get_event_count_for_team(team.id)
            instance_usage_summary["events_count_total"] += team_event_count
            team_report["events_count_total"] = team_event_count
            team_events_in_period_count = get_event_count_for_team_and_period(team.id, period_start, period_end)
            team_report["events_count_new_in_period"] = team_events_in_period_count
            instance_usage_summary["events_count_new_in_period"] += team_report["events_count_new_in_period"]

            team_report["events_count_by_lib"] = get_events_count_for_team_by_client_lib(
                team.id, period_start, period_end
            )
            team_report["events_count_by_name"] = get_events_count_for_team_by_event_type(
                team.id, period_start, period_end
            )

            team_report["duplicate_distinct_ids"] = count_duplicate_distinct_ids_for_team(team.id)
            team_report["multiple_ids_per_person"] = count_total_persons_with_multiple_ids(team.id)
            team_report["group_types_count"] = GroupTypeMapping.objects.filter(team_id=team.id).count()

            if team_report["group_types_count"] > 0:
                instance_usage_summary["using_groups"] = True
            # pull person stats and the rest here from Postgres always
            persons_considered_total = Person.objects.filter(team_id=team.id)
            persons_considered_total_new_in_period = persons_considered_total.filter(
                created_at__gte=period_start, created_at__lte=period_end,
            )
            team_report["persons_count_total"] = persons_considered_total.count()
            instance_usage_summary["persons_count_total"] += team_report["persons_count_total"]

            team_report["persons_count_new_in_period"] = persons_considered_total_new_in_period.count()
            instance_usage_summary["persons_count_new_in_period"] += team_report["persons_count_new_in_period"]

            # Dashboards
            team_dashboards = Dashboard.objects.filter(team=team).exclude(deleted=True)
            team_report["dashboards_count"] = team_dashboards.count()
            instance_usage_summary["dashboards_count"] += team_report["dashboards_count"]
            team_report["dashboards_template_count"] = team_dashboards.filter(creation_mode="template").count()
            team_report["dashboards_shared_count"] = team_dashboards.filter(is_shared=True).count()
            team_report["dashboards_tagged_count"] = team_dashboards.exclude(tagged_items__isnull=True).count()

            # Feature Flags
            feature_flags = FeatureFlag.objects.filter(team=team).exclude(deleted=True)
            team_report["ff_count"] = feature_flags.count()
            instance_usage_summary["ff_count"] += team_report["ff_count"]
            team_report["ff_active_count"] = feature_flags.filter(active=True).count()
            report["teams"][team.id] = team_report
        except Exception as err:
            capture_event("instance status report failure", {"error": str(err)}, dry_run=dry_run)

    report["instance_usage_summary"] = instance_usage_summary
    capture_event("instance status report", report, dry_run=dry_run)
    return report


def capture_event(name: str, report: Dict[str, Any], dry_run: bool) -> None:
    if not dry_run:
        posthoganalytics.api_key = "sTMFPsFhdP1Ssg"
        posthoganalytics.capture(
            get_machine_id(), name, {**report, "scope": "machine"}, groups={"instance": settings.SITE_URL}
        )

        if "instance_usage_summary" in report:
            posthoganalytics.group_identify("instance", settings.SITE_URL, fetch_instance_params(report))

        for user in User.objects.all():
            posthoganalytics.capture(user.distinct_id, f"user {name}", {**report, "scope": "user"})
    else:
        print(name, json.dumps(report))  # noqa: T001


def fetch_instance_params(report: Dict[str, Any]) -> dict:
    return {
        "site_url": settings.SITE_URL,
        "machine_id": get_machine_id(),
        "posthog_version": report["posthog_version"],
        "deployment": report["deployment"],
        "realm": report["realm"],
        **report["instance_usage_summary"],
    }


def fetch_event_counts_by_lib(params: Tuple[Any, ...]) -> dict:
    results = fetch_sql(
        """
        SELECT properties->>'$lib' as lib, COUNT(1) as count
        FROM posthog_event WHERE team_id = %s AND timestamp >= %s AND timestamp <= %s
        GROUP BY lib
        """,
        params,
    )
    return {result.lib: result.count for result in results}


def fetch_events_count_by_name(params: Tuple[Any, ...]) -> dict:
    results = fetch_sql(
        """
        SELECT event as name, COUNT(1) as count
        FROM posthog_event WHERE team_id = %s AND timestamp >= %s AND timestamp <= %s
        GROUP BY name
        """,
        params,
    )
    return {result.name: result.count for result in results}


def fetch_table_size(table_name: str) -> int:
    return fetch_sql("SELECT pg_total_relation_size(%s) as size", (table_name,))[0].size


def fetch_sql(sql_: str, params: Tuple[Any, ...]) -> List[Any]:
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL(sql_), params)
        return namedtuplefetchall(cursor)


def get_instance_licenses() -> List[str]:
    try:
        from ee.models import License
    except ImportError:
        return []
    else:
        return [license.key for license in License.objects.all()]
