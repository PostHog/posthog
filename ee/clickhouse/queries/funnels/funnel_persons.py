import datetime as dt
from typing import Any, Dict, List, cast

from ee.clickhouse.queries.clickhouse_session_recording import (
    query_sessions_for_funnel_persons,
    query_sessions_in_range,
)
from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel
from ee.clickhouse.sql.funnels.funnel import FUNNEL_PERSONS_BY_STEP_SQL
from posthog.models import Person


class ClickhouseFunnelPersons(ClickhouseFunnel):
    def get_query(self):
        return FUNNEL_PERSONS_BY_STEP_SQL.format(
            offset=self._filter.offset,
            steps_per_person_query=self.get_step_counts_query(),
            persons_steps=self._get_funnel_person_step_condition(),
            extra_columns=", timestamp",
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

        session_recordings = query_sessions_for_funnel_persons(
            self._team,
            self._filter.date_from,
            cast(dt.datetime, self._filter.date_to)
            + dt.timedelta(
                **{(self._filter.funnel_window_interval_unit or "day") + "s": self._filter.funnel_window_interval or 14}
            ),
            all_distinct_ids,
        )
        for row in session_recordings:
            person_uuid = str(row["person_id"])
            if not "session_recordings" in persons_uuid_map[person_uuid]:
                persons_uuid_map[person_uuid]["session_recordings"] = []
            persons_uuid_map[person_uuid]["session_recordings"].append(row)

        return persons_serialized, len(results) > cast(int, self._filter.limit) - 1
