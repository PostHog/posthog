import dataclasses
from typing import Dict, Optional, Sequence

from django.db.models import Q
from django.utils import timezone

from posthog.celery import app
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.tasks.usage_report import (
    find_count_for_team_in_rows,
    get_teams_with_event_count_in_period,
    get_teams_with_recording_count_in_period,
)
from posthog.utils import get_current_day


@dataclasses.dataclass
class UsageCounters:
    events: int
    recordings: int


RATE_LIMITER_CACHE_KEY = "@posthog-plugin-server/rate-limiter/"


# Cache ids of organizations that have been rate limited by the billing service
@app.task(ignore_result=True, retries=3)
def update_all_org_billing_rate_limiting(
    dry_run: bool = False,
    only_organization_id: Optional[str] = None,
) -> Dict[str, Dict[str, float]]:  # Dict[str, Any]]:

    period = get_current_day()
    period_start, period_end = period

    # Clickhouse is good at counting things so we count across all teams rather than doing it one by one
    all_data = dict(
        teams_with_event_count_in_period=get_teams_with_event_count_in_period(period_start, period_end),
        teams_with_recording_count_in_period=get_teams_with_recording_count_in_period(period_start, period_end),
    )

    teams: Sequence[Team] = list(
        Team.objects.select_related("organization").exclude(
            Q(organization__for_internal_metrics=True) | Q(is_demo=True)
        )
    )

    current_usage_reports: Dict[str, UsageCounters] = {}
    orgs_by_id: Dict[str, Organization] = {}

    # we iterate through all teams, and add their usage to the organization they belong to
    for team in teams:
        team_report = UsageCounters(
            events=find_count_for_team_in_rows(team.id, all_data["teams_with_event_count_in_period"]),
            recordings=find_count_for_team_in_rows(team.id, all_data["teams_with_recording_count_in_period"]),
        )

        org_id = str(team.organization.id)

        if org_id not in current_usage_reports:
            orgs_by_id[org_id] = team.organization
            current_usage_reports[org_id] = team_report
        else:
            org_report = current_usage_reports[org_id]
            # Iterate on all fields of the UsageCounters and add the values from the team report to the org report
            for field in dataclasses.fields(UsageCounters):
                if hasattr(team_report, field.name):
                    setattr(
                        org_report,
                        field.name,
                        getattr(org_report, field.name) + getattr(team_report, field.name),
                    )

    rate_limited_orgs: Dict[str, Dict[str, float]] = {"events": {}, "recordings": {}}

    redis_client = get_client()

    for org_id in current_usage_reports.keys():
        org = orgs_by_id[org_id]

        if only_organization_id and only_organization_id != org_id:
            continue

        # if we don't have limits set from the billing service, we can't risk rate limiting existing customers
        if org.usage:
            # for each organization, we check if the current usage + today's unreported usage is over the limit
            for field in dataclasses.fields(UsageCounters):
                usage = org.usage.get("events", {}).get("usage", 0)
                limit = org.usage.get("recordings", {}).get("limit", 0)
                unreported_usage = getattr(current_usage_reports[org_id], field.name)

                is_rate_limited = usage + unreported_usage > limit
                if is_rate_limited:
                    rate_limited_orgs[field.name][org_id] = timezone.now().timestamp()

    if not dry_run:
        # we store the rate limited orgs in redis, so that the plugin server can check if an org is rate limited
        for field in dataclasses.fields(UsageCounters):
            org_mapping = rate_limited_orgs[field.name]
            if org_mapping != {}:
                redis_client.zadd(
                    f"{RATE_LIMITER_CACHE_KEY}{field.name}",
                    org_mapping,  # type: ignore
                ),

    return rate_limited_orgs
