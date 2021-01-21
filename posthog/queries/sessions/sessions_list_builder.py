from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from posthog.models.filters.mixins.utils import cached_property
from posthog.utils import flatten

RunningSession = Dict
Session = Dict
EventWithCurrentUrl = Tuple  # distinct_id, timestamp, current_url, bools (action_filter_matches action_filter)

SESSION_TIMEOUT = timedelta(minutes=30)
MAX_SESSION_DURATION = timedelta(hours=8)


class SessionListBuilder:
    def __init__(
        self,
        events_iterator,
        last_page_last_seen={},
        emails={},
        limit=50,
        offset=0,
        action_filter_count=0,
        session_timeout=SESSION_TIMEOUT,
        max_session_duration=MAX_SESSION_DURATION,
    ):
        self.iterator = events_iterator
        self.last_page_last_seen: Dict[str, int] = last_page_last_seen
        self.emails: Dict[str, Optional[str]] = emails
        self.limit: int = limit
        self.offset: int = offset
        self.action_filter_count: int = action_filter_count
        self.session_timeout: timedelta = session_timeout
        self.max_session_duration: timedelta = max_session_duration
        self.sessions_count = 0

        self.running_sessions: Dict[str, RunningSession] = {}
        self._sessions: List[Session] = []

    @cached_property
    def sessions(self):
        sessions = list(sorted(self._sessions, key=lambda session: session["end_time"], reverse=True))[: self.limit]
        return sessions

    @cached_property
    def pagination(self):
        has_more = len(self._sessions) >= self.limit and (
            len(self._sessions) > self.limit or next(self.iterator, None) is not None
        )

        if has_more:
            return {
                "offset": self.offset + self.limit,
                "last_seen": self.next_page_last_seen(),
                "start_timestamp": self.next_page_start_timestamp,
            }
        else:
            return None

    @cached_property
    def next_page_start_timestamp(self):
        return min(session["end_time"].timestamp() for session in self.sessions)

    def next_page_last_seen(self):
        """
        Returns { distinct_id -> timestamp } mapping. All events >= timestamp should be ignored by that person

        This is needed to make pagination work.
        """
        result = {}
        for distinct_id, timestamp in self.last_page_last_seen.items():
            if timestamp <= self.next_page_start_timestamp:
                result[distinct_id] = timestamp

        for session in self.sessions:
            result[session["distinct_id"]] = int(session["start_time"].timestamp())
        return result

    def build(self):
        for index, event in enumerate(self.iterator):
            distinct_id, timestamp, *rest = event
            if (
                distinct_id not in self.last_page_last_seen
                or timestamp.timestamp() < self.last_page_last_seen[distinct_id]
            ):
                if distinct_id in self.running_sessions:
                    if self._has_session_timed_out(distinct_id, timestamp):
                        self._session_end(distinct_id)
                        self._session_start(event)
                    else:
                        self._session_update(event)
                elif len(self.running_sessions) + self.sessions_count < self.limit:
                    self._session_start(event)

            if index % 300 == 0:
                self._sessions_check(timestamp)

            if self.sessions_count >= self.limit:
                break

        self._sessions_check(None)

    def _session_start(self, event: EventWithCurrentUrl):
        distinct_id, timestamp, id, current_url, *action_filter_matches = event
        self.running_sessions[distinct_id] = {
            "distinct_id": distinct_id,
            "end_time": timestamp,
            "event_count": 0,
            "start_url": current_url,
            "email": self.emails.get(distinct_id),
            "matching_events": [[] for _ in range(self.action_filter_count)],
        }
        self._session_update(event)

    def _session_update(self, event: EventWithCurrentUrl):
        distinct_id, timestamp, id, current_url, *action_filter_matches = event
        self.running_sessions[distinct_id]["start_time"] = timestamp
        self.running_sessions[distinct_id]["event_count"] += 1
        self.running_sessions[distinct_id]["end_url"] = current_url

        for index, is_match in enumerate(action_filter_matches):
            if is_match:
                self.running_sessions[distinct_id]["matching_events"][index].append(id)

    def _session_end(self, distinct_id: str):
        self.sessions_count += 1
        session = self.running_sessions[distinct_id]
        # :TRICKY: Remove sessions where some filtered actions did not occur _after_ limiting to avoid running into pagination issues
        if self.action_filter_count == 0 or all(len(ids) > 0 for ids in session["matching_events"]):
            self._sessions.append(
                {
                    **session,
                    "matching_events": list(sorted(set(flatten(session["matching_events"])))),
                    "global_session_id": f"{distinct_id}-{session['start_time']}",
                    "length": (session["end_time"] - session["start_time"]).seconds,
                }
            )
        del self.running_sessions[distinct_id]

    def _has_session_timed_out(self, distinct_id: str, timestamp: datetime):
        session = self.running_sessions[distinct_id]
        return (
            session["start_time"] - timestamp > self.session_timeout
            or session["end_time"] - session["start_time"] > self.max_session_duration
        )

    def _sessions_check(self, timestamp: Optional[datetime]):
        for distinct_id in list(self.running_sessions.keys()):
            if timestamp is None or self._has_session_timed_out(distinct_id, timestamp):
                self._session_end(distinct_id)
