from typing import Any, List

from django.db.models import F, Max, Min

from posthog.models import Event, Team


# :TRICKY: This mutates sessions list
def add_session_recording_ids(team: Team, sessions_results: List[Any]) -> List[Any]:
    min_ts = min(it["start_time"] for it in sessions_results)
    max_ts = max(it["end_time"] for it in sessions_results)

    session_recordings = (
        Event.objects.filter(team=team, event="$snapshot")
        .values("distinct_id", "properties__$session_id")
        .annotate(start_time=Min("timestamp"), end_time=Max("timestamp"))
        .filter(start_time__lte=F("end_time"), end_time__gte=F("start_time"))
    )

    for session in sessions_results:
        session["session_recording_ids"] = [
            recording["properties__$session_id"] for recording in session_recordings if matches(session, recording)
        ]
    return sessions_results


def matches(session: Any, session_recording: Any) -> bool:
    return (
        session["distinct_id"] == session_recording["distinct_id"]
        and session["start_time"] <= session_recording["end_time"]
        and session["end_time"] >= session_recording["start_time"]
    )
