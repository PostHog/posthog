import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from django.db.models import F, Max, Min

from posthog.models import Filter, Person, SessionRecordingEvent, Team
from posthog.queries.base import BaseQuery

DistinctId = str
Snapshots = List[Any]


class SessionRecording:
    def query_recording_snapshots(self, team: Team, session_id: str) -> Tuple[Optional[DistinctId], Snapshots]:
        events = SessionRecordingEvent.objects.filter(team=team, session_id=session_id)

        if len(events) == 0:
            return None, []

        return events[0].distinct_id, [e.snapshot_data for e in events]

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> Dict[str, Any]:
        from posthog.api.person import PersonSerializer

        distinct_id, snapshots = self.query_recording_snapshots(team, kwargs["session_recording_id"])
        person = (
            PersonSerializer(Person.objects.get(team=team, persondistinctid__distinct_id=distinct_id)).data
            if distinct_id
            else None
        )

        return {"snapshots": list(sorted(snapshots, key=lambda s: s["timestamp"])), "person": person}


def query_sessions_in_range(team: Team, start_time: datetime.datetime, end_time: datetime.datetime) -> List[dict]:
    return list(
        SessionRecordingEvent.objects.filter(team=team)
        .values("distinct_id", "session_id")
        .annotate(start_time=Min("timestamp"), end_time=Max("timestamp"))
        .filter(start_time__lte=F("end_time"), end_time__gte=F("start_time"))
    )


# :TRICKY: This mutates sessions list
def add_session_recording_ids(
    team: Team, sessions_results: List[Any], query: Callable = query_sessions_in_range
) -> List[Any]:
    if len(sessions_results) == 0:
        return sessions_results

    min_ts = min(it["start_time"] for it in sessions_results)
    max_ts = max(it["end_time"] for it in sessions_results)

    session_recordings = query(team, min_ts, max_ts)

    for session in sessions_results:
        session["session_recording_ids"] = [
            recording["session_id"] for recording in session_recordings if matches(session, recording)
        ]
    return sessions_results


def matches(session: Any, session_recording: Any) -> bool:
    return (
        session["distinct_id"] == session_recording["distinct_id"]
        and session["start_time"] <= session_recording["end_time"]
        and session["end_time"] >= session_recording["start_time"]
    )
