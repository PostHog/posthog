import datetime

from posthog.models import Team
from posthog.schema import RecordingsQuery
from posthog.session_recordings.queries.session_recording_list_from_query import (
    SessionRecordingQueryResult,
    SessionRecordingListFromQuery,
)
from posthog.session_recordings.session_recording_api import query_as_params_to_dict
from posthog.test.base import _create_event


def create_event(
    distinct_id: str,
    timestamp: datetime.datetime,
    team: Team,
    event_name: str = "$pageview",
    properties: dict | None = None,
) -> str:
    if properties is None:
        properties = {"$os": "Windows 95", "$current_url": "aloha.com/2"}
    return _create_event(
        team=team,
        event=event_name,
        timestamp=timestamp,
        distinct_id=distinct_id,
        properties=properties,
    )


def filter_recordings_by(team: Team, recordings_filter: dict) -> SessionRecordingQueryResult:
    the_query = RecordingsQuery.model_validate(query_as_params_to_dict(recordings_filter or {}))
    session_recording_list_instance = SessionRecordingListFromQuery(
        query=the_query, team=team, hogql_query_modifiers=None
    )
    return session_recording_list_instance.run()
