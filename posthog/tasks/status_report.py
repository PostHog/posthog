import logging
from typing import Any, Dict

import posthoganalytics
from django.db import connection
from psycopg2 import sql  # type: ignore

from posthog.models import Event, Team, User
from posthog.models.utils import namedtuplefetchall
from posthog.utils import get_machine_id, get_previous_week
from posthog.version import VERSION

logger = logging.getLogger(__name__)


def status_report(*, dry_run: bool = False) -> Dict[str, Any]:
    period_start, period_end = get_previous_week()
    report: Dict[str, Any] = {
        "posthog_version": VERSION,
        "period": {"start_inclusive": period_start.isoformat(), "end_inclusive": period_end.isoformat()},
    }
    report["users_who_logged_in"] = [
        {"id": user.id, "distinct_id": user.distinct_id}
        if user.anonymize_data
        else {"id": user.id, "distinct_id": user.distinct_id, "first_name": user.first_name, "email": user.email}
        for user in User.objects.filter(last_login__gte=period_start)
    ]
    report["teams"] = {}
    for team in Team.objects.all():
        team_report: Dict[str, Any] = {}
        events_considered_total = Event.objects.filter(team_id=team.id)
        events_considered_new_in_period = events_considered_total.filter(
            created_at__gte=period_start, created_at__lte=period_end,
        )
        persons_considered_total = Event.objects.filter(team_id=team.id)
        persons_considered_total_new_in_period = persons_considered_total.filter(
            created_at__gte=period_start, created_at__lte=period_end,
        )
        team_report["events_count_total"] = events_considered_total.count()
        team_report["events_count_new_in_period"] = events_considered_new_in_period.count()
        team_report["persons_count_total"] = persons_considered_total.count()
        team_report["persons_count_new_in_period"] = persons_considered_total_new_in_period.count()

        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    """
                SELECT COUNT(DISTINCT person_id) as persons_count
                FROM posthog_event JOIN posthog_persondistinctid ON (posthog_event.distinct_id = posthog_persondistinctid.distinct_id) WHERE posthog_event.team_id = %s AND posthog_event.created_at >= %s AND posthog_event.created_at <= %s
            """
                ),
                (team.id, report["period"]["start_inclusive"], report["period"]["end_inclusive"]),
            )
            team_report["persons_count_active_in_period"] = cursor.fetchone()[0]
            cursor.execute(
                sql.SQL(
                    """
                SELECT properties->>'$lib' as lib, COUNT(*) as count
                FROM posthog_event WHERE team_id = %s AND created_at >= %s AND created_at <= %s GROUP BY lib
            """
                ),
                (team.id, report["period"]["start_inclusive"], report["period"]["end_inclusive"]),
            )
            team_report["events_count_by_lib"] = {result.lib: result.count for result in namedtuplefetchall(cursor)}
            cursor.execute(
                sql.SQL(
                    """
                SELECT event as name, COUNT(*) as count
                FROM posthog_event WHERE team_id = %s AND created_at >= %s AND created_at <= %s GROUP BY name
            """
                ),
                (team.id, report["period"]["start_inclusive"], report["period"]["end_inclusive"]),
            )
            team_report["events_count_by_name"] = {result.name: result.count for result in namedtuplefetchall(cursor)}
        report["teams"][team.id] = team_report
    if not dry_run:
        posthoganalytics.api_key = "sTMFPsFhdP1Ssg"
        disabled = posthoganalytics.disabled
        posthoganalytics.disabled = False
        posthoganalytics.capture(get_machine_id(), "instance status report", report)
        posthoganalytics.disabled = disabled
    return report
