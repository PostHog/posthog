from collections import defaultdict
from datetime import timedelta
from typing import Dict, List

from celery import shared_task
from dateutil import parser
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.timezone import now

from posthog.models import SessionRecordingEvent, Team

RETENTION_PERIOD = timedelta(days=7)
SESSION_CUTOFF = timedelta(minutes=30)


def session_recording_retention_scheduler() -> None:
    for team in Team.objects.all().filter(session_recording_retention_period_days__isnull=False):
        time_threshold = now() - timedelta(days=team.session_recording_retention_period_days)
        session_recording_retention.delay(team_id=team.id, time_threshold=time_threshold)


@shared_task(ignore_result=True, max_retries=1)
def session_recording_retention(team_id: int, time_threshold: str) -> None:
    time_threshold_dt = parser.isoparse(time_threshold)
    events = SessionRecordingEvent.objects.filter(team_id=team_id, timestamp__lte=time_threshold_dt).order_by(
        "timestamp"
    )
    purged_sessions = {
        session_id: events
        for session_id, events in build_sessions(events).items()
        if not close_to_threshold(time_threshold_dt, events)
    }

    primary_keys = [event.pk for session_events in purged_sessions.values() for event in session_events]
    SessionRecordingEvent.objects.filter(pk__in=primary_keys).delete()


def build_sessions(events: QuerySet) -> Dict[str, List[SessionRecordingEvent]]:
    sessions = defaultdict(list)
    for event in events:
        sessions[event.session_id].append(event)
    return sessions


# If last event of session was within 30 minutes of threshold, it may be cut in half.
#
# Closely coupled with semantics in session queries
def close_to_threshold(time_threshold: timezone.datetime, session_events: List[SessionRecordingEvent]) -> bool:
    last_event_time = session_events[-1].timestamp
    return (time_threshold - last_event_time) <= SESSION_CUTOFF
