import datetime

from posthog.models import Team
from posthog.schema import RecordingsQuery
from posthog.session_recordings.queries_to_replace.session_recording_list_from_query import (
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


def filter_recordings_by(team: Team, recordings_filter: dict | None = None) -> SessionRecordingQueryResult:
    the_query = RecordingsQuery.model_validate(query_as_params_to_dict(recordings_filter or {}))
    session_recording_list_instance = SessionRecordingListFromQuery(
        query=the_query, team=team, hogql_query_modifiers=None
    )
    return session_recording_list_instance.run()


def assert_query_matches_session_ids(
    team: Team, query: dict | None, expected: list[str], sort_results_when_asserting: bool = True
) -> None:
    (session_recordings, more_recordings_available, _) = filter_recordings_by(team=team, recordings_filter=query)

    # in some tests we care about the order of results e.g. when testing sorting
    # generally we want to sort results since the order is not guaranteed
    # e.g. we're using UUIDs for the IDs
    if sort_results_when_asserting:
        assert sorted([sr["session_id"] for sr in session_recordings]) == sorted(expected)
    else:
        assert [sr["session_id"] for sr in session_recordings] == expected

    assert more_recordings_available is False
