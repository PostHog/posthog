from collections import defaultdict
from datetime import timedelta
from typing import Dict, List

from celery import shared_task
from django.db import connection, transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.timezone import now
from sentry_sdk import capture_exception

from posthog.models import SessionRecordingEvent, Team

RETENTION_PERIOD = timedelta(days=7)
SESSION_CUTOFF = timedelta(minutes=30)


@shared_task(ignore_result=True, max_retries=1)
def session_recording_retention(team_id: int, time_threshold: str) -> None:
    cursor = connection.cursor()
    try:
        # This deletes events, but may cut sessions in half, this is by choice for performance reasons
        cursor.execute(
            "DELETE FROM posthog_sessionrecordingevent WHERE team_id = %s AND timestamp < %s", [team_id, time_threshold]
        )
    except Exception as err:
        capture_exception(err)


def build_sessions(events: QuerySet) -> Dict[str, List[SessionRecordingEvent]]:
    sessions = defaultdict(list)
    for event in events:
        sessions[event.session_id].append(event)
    return sessions
