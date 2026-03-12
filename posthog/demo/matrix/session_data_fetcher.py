"""
Fetch real session data from PostHog for session replay generation.
"""

import json
import datetime as dt
from typing import Optional

from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from .session_replay_generator import ReplayableSession, ReplayEvent, ReplayPerson


class SessionDataFetcher:
    """Fetches real session data from PostHog database for replay generation."""

    team: Team

    def __init__(self, team: Team):
        self.team = team

    def fetch_sessions_for_replay(self, max_sessions: int = 10, days_back: int = 90) -> list[ReplayableSession]:
        cutoff_date = timezone.now() - dt.timedelta(days=days_back)

        session_ids = self._get_session_ids_in_range(cutoff_date, max_sessions)

        if not session_ids:
            return []

        sessions_data = self._get_events_for_sessions(session_ids)

        # Convert to ReplayableSession objects
        replayable_sessions = []
        for session_id, events_data in sessions_data.items():
            replayable_session = self._create_replayable_session(session_id, events_data)
            if replayable_session:
                replayable_sessions.append(replayable_session)

        return replayable_sessions

    def _get_session_ids_in_range(self, cutoff_date: dt.datetime, max_sessions: int) -> list[str]:
        # Get sessions between 1-5 minutes, pick the ones with the most events
        # We fetch a pool of candidates and then select the most active ones
        pool_size = max_sessions * 10  # Fetch a larger pool to select from
        response = execute_hogql_query(
            query="""
            SELECT
                properties.$session_id as sid,
                count() as event_count
            FROM events
            WHERE properties.$session_id IN (
                SELECT id
                FROM sessions
                WHERE $start_timestamp > {cutoff_date}
                  AND duration >= 60
                  AND duration < 300
                LIMIT {pool_size}
            )
            GROUP BY sid
            ORDER BY event_count DESC
            LIMIT {limit}
            """,
            team=self.team,
            placeholders={
                "cutoff_date": ast.Constant(value=cutoff_date),
                "pool_size": ast.Constant(value=pool_size),
                "limit": ast.Constant(value=max_sessions),
            },
        )
        return [row[0] for row in response.results]

    def _get_events_for_sessions(self, session_ids: list[str]) -> dict[str, list[dict]]:
        response = execute_hogql_query(
            query="""
            SELECT properties.$session_id as session_id,
                   event,
                   timestamp,
                   properties,
                   distinct_id,
                   person_id
            FROM events
            WHERE properties.$session_id IN {session_ids_tuple}
            ORDER BY properties.$session_id, timestamp
        """,
            team=self.team,
            placeholders={"session_ids_tuple": ast.Constant(value=session_ids)},
        )

        # Group by session_id
        sessions_data = {}
        for row in response.results or []:
            session_id, event, timestamp, properties, distinct_id, person_id = row
            if session_id not in sessions_data:
                sessions_data[session_id] = []

            # Parse properties JSON if it's a string
            parsed_properties = {}
            if properties:
                if isinstance(properties, str):
                    try:
                        parsed_properties = json.loads(properties)
                    except (json.JSONDecodeError, TypeError):
                        parsed_properties = {}
                else:
                    parsed_properties = properties

            sessions_data[session_id].append(
                {
                    "event": event,
                    "timestamp": timestamp,
                    "properties": parsed_properties,
                    "distinct_id": distinct_id,
                    "person_id": person_id,
                }
            )

        return sessions_data

    def _create_replayable_session(self, session_id: str, events_data: list[dict]) -> Optional[ReplayableSession]:
        first_event = events_data[0]
        distinct_id = first_event["distinct_id"]

        person_properties = self._get_person_properties(distinct_id)
        person = ReplayPerson(
            email=person_properties.get("email", f"{distinct_id}@example.com"),
            name=person_properties.get("name", f"User {distinct_id[:8]}"),
            distinct_id=distinct_id,
        )

        # Create ReplayEvent objects
        events = []
        for event_data in events_data:
            events.append(
                ReplayEvent(
                    event=event_data["event"],
                    timestamp=event_data["timestamp"],
                    properties=event_data["properties"],
                    distinct_id=event_data["distinct_id"],
                )
            )

        # Get session start/end times
        start_time = events[0].timestamp
        end_time = events[-1].timestamp

        return ReplayableSession(
            person=person, events=events, start_time=start_time, end_time=end_time, session_id=session_id
        )

    def _get_person_properties(self, distinct_id: str) -> dict:
        response = execute_hogql_query(
            query="""
            SELECT properties
            FROM persons
            WHERE id IN (
                SELECT person_id
                FROM person_distinct_ids
                WHERE distinct_id = {distinct_id}
            )
            LIMIT 1""",
            team=self.team,
            placeholders={"distinct_id": ast.Constant(value=distinct_id)},
        )
        return json.loads(response.results[0][0]) if response.results else {}
