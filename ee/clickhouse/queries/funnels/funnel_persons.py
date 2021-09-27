import datetime as dt
from typing import Any, Dict, List, Optional, cast

from ee.clickhouse.queries.clickhouse_session_recording import query_sessions_for_funnel_persons
from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel
from ee.clickhouse.sql.funnels.funnel import FUNNEL_PERSONS_BY_STEP_SQL
from posthog.models.filters.filter import Filter
from posthog.models.person import Person
from posthog.models.session_recording_event import SessionRecordingViewed
from posthog.models.team import Team
from posthog.models.user import User
from posthog.queries.sessions.session_recording import collect_matching_recordings


class ClickhouseFunnelPersons(ClickhouseFunnel):
    _user: Optional[User]

    def __init__(self, *args, user: Optional[User] = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._user = user

    def get_query(self):
        return FUNNEL_PERSONS_BY_STEP_SQL.format(
            offset=self._filter.offset,
            steps_per_person_query=self.get_step_counts_query(),
            persons_steps=self._get_funnel_person_step_condition(),
            extra_fields=self._get_timestamp_outer_select(),
        )

    def _format_results(self, results):
        persons = Person.objects.filter(team_id=self._team.pk, uuid__in=[val[0] for val in results])

        from posthog.api.person import PersonSerializer

        persons_serialized = PersonSerializer(persons, many=True).data

        persons_uuid_map: Dict[str, Dict[str, Any]] = {}
        all_distinct_ids: List[str] = []
        for person in persons_serialized:
            persons_uuid_map[str(person["uuid"])] = person
            all_distinct_ids.extend(person["distinct_ids"])

        window_timedelta = dt.timedelta(
            **{f"{self._filter.funnel_window_interval_unit}s": self._filter.funnel_window_interval}
        )
        session_recordings = query_sessions_for_funnel_persons(
            self._team,
            # We are sure that date_from and date_to have values here, as they're ensured in the superclass
            cast(dt.datetime, self._filter.date_from),
            cast(dt.datetime, self._filter.date_to) + window_timedelta,
            all_distinct_ids,
        )
        if session_recordings:
            viewed_session_recordings = (
                set(
                    SessionRecordingViewed.objects.filter(team=self._team, user_id=self._user.id).values_list(
                        "session_id", flat=True
                    )
                )
                if self._user is not None
                else set()
            )
            for row in collect_matching_recordings(None, session_recordings, None, viewed_session_recordings):
                row["person_id"] = str(row["person_id"])
                row["start_time"] = row["start_time"].isoformat()
                row["end_time"] = row["end_time"].isoformat()
                person_uuid = row["person_id"]
                if not "session_recordings" in persons_uuid_map[person_uuid]:
                    persons_uuid_map[person_uuid]["session_recordings"] = []
                persons_uuid_map[person_uuid]["session_recordings"].append(row)

        return persons_serialized, len(results) > cast(int, self._filter.limit) - 1
