import logging
import os
from typing import Any, Dict, List, Type

from ee.clickhouse.models.event import (
    get_agg_event_count_for_teams,
    get_agg_event_count_for_teams_and_period,
    get_events_TEST,
)
from posthog.event_usage import report_org_usage_failure
from posthog.models import Team, User
from posthog.tasks.status_report import get_instance_licenses
from posthog.utils import get_instance_realm, get_previous_day
from posthog.version import VERSION

logger = logging.getLogger(__name__)


def event_usage_report() -> Dict[str, Any]:
    distinct_id = User.objects.first().distinct_id
    period_start, period_end = get_previous_day()
    month_start = period_start.replace(day=1)
    report: Dict[str, Any] = {
        "posthog_version": VERSION,
        "deployment": os.getenv("DEPLOYMENT", "unknown"),
        "realm": get_instance_realm(),
        "period": {"start_inclusive": period_start.isoformat(), "end_inclusive": period_end.isoformat()},
        "site_url": os.getenv("SITE_URL", "unknown"),
        "license_keys": get_instance_licenses(),
    }

    default_instance_usage: Dict[str, int] = {
        "events_count_total": 0,
        "events_count_new_in_period": 0,
        "events_count_month_to_date": 0,
    }

    instance_usage_by_org: Dict[str, Any] = {}
    org_teams: Dict[str, List[str]] = {}

    for team in Team.objects.exclude(organization__for_internal_metrics=True):
        org = str(team.organization.id)
        if org in org_teams:
            org_teams[org].append(team.id)
        else:
            org_teams[org] = [team.id]

    for org, teams in org_teams.items():
        usage = default_instance_usage
        try:
            usage["events_count_total"] += get_agg_event_count_for_teams(teams)
            usage["events_count_new_in_period"] += get_agg_event_count_for_teams_and_period(
                teams, period_start, period_end
            )
            usage["events_count_month_to_date"] += get_agg_event_count_for_teams_and_period(
                teams, month_start, period_end
            )
            instance_usage_by_org[org] = usage

        except Exception as err:
            report_org_usage_failure(distinct_id, err)

    report["instance_usage_by_org"] = instance_usage_by_org
    return report
