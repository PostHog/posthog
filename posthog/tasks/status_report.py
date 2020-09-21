import logging
from datetime import datetime, timedelta
from typing import Any, Dict

import posthoganalytics
from celery.utils.functional import first
from django.db import connection
from psycopg2 import sql  # type: ignore

from posthog.models import Event, User
from posthog.models.utils import namedtuplefetchall
from posthog.utils import get_machine_id
from posthog.version import VERSION

logger = logging.getLogger(__name__)


def status_report() -> None:
    period_end = (datetime.utcnow() - timedelta(datetime.utcnow().weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )  # very start of the current Monday
    period_start = period_end - timedelta(7)  # very start of the Monday preceding the current one
    report: Dict[str, Any] = {
        "period": {"start_inclusive": period_start.isoformat(), "end_exclusive": period_end.isoformat()}
    }
    report["posthog_version"] = VERSION
    report["users_who_logged_in"] = [
        {"id": user.id}
        if user.anonymize_data
        else {"id": user.id, "distinct_id": user.distinct_id, "first_name": user.first_name, "email": user.email}
        for user in User.objects.filter(last_login__gte=period_start)
    ]
    events_considered = Event.objects.filter(created_at__gte=period_start, created_at__lt=period_end)
    report["events_count_total"] = events_considered.count()
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                """
            SELECT properties->>'$lib' as lib, COUNT(*) as count
            FROM posthog_event WHERE created_at >= %s AND created_at < %s GROUP BY lib
        """
            ),
            (report["period"]["start_inclusive"], report["period"]["end_exclusive"]),
        )
        report["events_count_by_lib"] = {result.lib: result.count for result in namedtuplefetchall(cursor)}
        cursor.execute(
            sql.SQL(
                """
            SELECT event as name, COUNT(*) as count
            FROM posthog_event WHERE created_at >= %s AND created_at < %s GROUP BY name
        """
            ),
            (report["period"]["start_inclusive"], report["period"]["end_exclusive"]),
        )
        report["events_count_by_name"] = {result.name: result.count for result in namedtuplefetchall(cursor)}
    posthoganalytics.api_key = "sTMFPsFhdP1Ssg"
    posthoganalytics.capture(get_machine_id(), "instance status report", report)
