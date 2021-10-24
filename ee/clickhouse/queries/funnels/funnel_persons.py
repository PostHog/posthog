from typing import List, Optional, cast

from ee.clickhouse.queries.clickhouse_session_recording import join_funnel_persons_with_session_recordings
from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel
from ee.clickhouse.sql.funnels.funnel import FUNNEL_PERSONS_BY_STEP_SQL
from posthog.models import Person, User


class ClickhouseFunnelPersons(ClickhouseFunnel):
    _user: Optional[User]

    def __init__(self, *args, user: Optional[User] = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._user = user

    def get_query(self, extra_fields: Optional[List[str]] = None):
        extra_fields_string = ", ".join([self._get_timestamp_outer_select()] + (extra_fields or []))
        return FUNNEL_PERSONS_BY_STEP_SQL.format(
            offset=self._filter.offset,
            steps_per_person_query=self.get_step_counts_query(),
            persons_steps=self._get_funnel_person_step_condition(),
            extra_fields=extra_fields_string,
            limit="" if self._no_person_limit else "LIMIT %(limit)s",
        )

    def _format_results(self, results):
        persons = Person.objects.filter(team_id=self._team.pk, uuid__in=[val[0] for val in results])
        from posthog.api.person import PersonSerializer

        persons_serialized = list(PersonSerializer(persons, many=True).data)
        if self._user is not None:
            join_funnel_persons_with_session_recordings(persons_serialized, self._filter, self._team, self._user.pk)

        return persons_serialized, len(results) > cast(int, self._filter.limit) - 1
