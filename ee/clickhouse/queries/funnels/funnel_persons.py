from typing import Any, Dict, List, Optional, Tuple, cast

from ee.clickhouse.queries.actor_base_query import ActorBaseQuery
from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel
from ee.clickhouse.sql.funnels.funnel import FUNNEL_PERSONS_BY_STEP_SQL
from ee.clickhouse.sql.person import GET_ACTORS_FROM_EVENT_QUERY
from posthog.models import Person
from posthog.models.filters.filter import Filter
from posthog.models.team import Team


class ClickhouseFunnelPersons(ClickhouseFunnel, ActorBaseQuery):

    _should_join_persons = True
    _extra_person_fields = ["created_at", "person_props", "is_identified"]
    _extra_aggregated_person_fields = {
        "created_at": f"any(created_at)",
        "properties": f"any(person_props)",
        "is_identified": f"any(is_identified)",
        "distinct_ids": f"arrayReduce('groupUniqArray', groupArray(distinct_id))",
    }

    def people_query(self) -> Tuple[str, Dict]:
        extra_fields_string = " ".join(f", {key}" for key in self._extra_aggregated_person_fields.keys())
        return (
            FUNNEL_PERSONS_BY_STEP_SQL.format(
                offset=self._filter.offset,
                steps_per_person_query=self.get_step_counts_query(),
                persons_steps=self._get_funnel_person_step_condition(),
                extra_fields=extra_fields_string,
                limit="" if self._no_person_limit else "LIMIT %(limit)s",
            ),
            self.params,
        )

    def groups_query(self) -> Tuple[str, Dict]:
        pass

    def get_query(self, extra_fields: Optional[List[str]] = None):
        extra_fields_string = " ".join(f", {key}" for key in self._extra_aggregated_person_fields.keys())
        return FUNNEL_PERSONS_BY_STEP_SQL.format(
            offset=self._filter.offset,
            steps_per_person_query=self.get_step_counts_query(),
            persons_steps=self._get_funnel_person_step_condition(),
            extra_fields=extra_fields_string,
            limit="" if self._no_person_limit else "LIMIT %(limit)s",
        )

    def _format_results(self, results):
        people = Person.objects.filter(team_id=self._team.pk, uuid__in=[val[0] for val in results])

        from posthog.api.person import PersonSerializer

        return PersonSerializer(people, many=True).data, len(results) > cast(int, self._filter.limit) - 1
