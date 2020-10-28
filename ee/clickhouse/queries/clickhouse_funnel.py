from collections import defaultdict
from typing import Any, Dict, List, Tuple

from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.funnels.funnel import FUNNEL_SQL
from ee.clickhouse.sql.funnels.step_action import STEP_ACTION_SQL
from ee.clickhouse.sql.funnels.step_event import STEP_EVENT_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filter import Filter
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.queries.funnel import Funnel
from posthog.utils import relative_date_parse


class ClickhouseFunnel(Funnel):
    _filter: Filter
    _team: Team
    _should_join_person: bool

    def __init__(self, filter: Filter, team: Team) -> None:
        self._filter = filter
        self._team = team

        self._should_join_person = False
        for entity in self._filter.entities:
            for entity_prop in entity.properties:
                if entity_prop.type == "person":
                    self._should_join_person = True

    def _build_filters(self, entity: Entity, index: int) -> str:
        prop_filters, prop_filter_params = parse_prop_clauses(
            "uuid", entity.properties, self._team, prepend=str(index), json_extract=True
        )
        self.params.update(prop_filter_params)
        if entity.properties:
            return prop_filters
        return ""

    def _build_steps_query(self, entity: Entity, index: int) -> str:
        parsed_date_from, parsed_date_to = parse_timestamps(filter=self._filter)
        is_first_step = (
            "timestamp <> toDateTime(0)"
            if index == 0
            else "step_{prev_step} <> toDateTime(0) AND timestamp >= step_{prev_step}".format(prev_step=index - 1)
        )
        filters = self._build_filters(entity, index)
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=entity.id)
            action_query, action_params = format_action_filter(action, "step_{}".format(index))
            if action_query == "":
                return ""

            self.params.update(action_params)
            content_sql = STEP_ACTION_SQL.format(actions_query=action_query, filters=filters,)
        else:
            content_sql = STEP_EVENT_SQL.format(event=entity.id, filters=filters)
        return content_sql

    def _exec_query(self) -> List[Tuple]:
        prop_filters, prop_filter_params = parse_prop_clauses(
            "uuid", self._filter.properties, self._team, prepend="global"
        )

        # format default dates
        if not self._filter._date_from:
            self._filter._date_from = relative_date_parse("-7d")
        if not self._filter._date_to:
            self._filter._date_to = timezone.now()

        parsed_date_from, parsed_date_to = parse_timestamps(filter=self._filter, table="events.")
        self.params: Dict = {"team_id": self._team.pk, **prop_filter_params}
        steps = [self._build_steps_query(entity, index) for index, entity in enumerate(self._filter.entities)]
        query = FUNNEL_SQL.format(
            select_steps=",".join(["step_{}".format(index) for index, _ in enumerate(self._filter.entities)]),
            team_id=self._team.id,
            steps=", ".join(steps),
            filters=prop_filters.replace("uuid IN", "events.uuid IN", 1),
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            person_prop_join="JOIN (SELECT id, properties FROM person WHERE team_id = %(team_id)s) as person ON person_distinct_id.person_id = person.id"
            if self._should_join_person
            else "",
            person_prop_alias="groupArray(person.properties) as person_props," if self._should_join_person else "",
        )
        return sync_execute(query, self.params)

    def data_to_return(self, results: List[Person]) -> List[Dict[str, Any]]:
        steps = []
        person_score: Dict = defaultdict(int)
        for index, funnel_step in enumerate(self._filter.entities):
            relevant_people = []
            for person in results:
                if person.max_step <= index:
                    person_score[person.uuid] += 1
                    relevant_people.append(person.uuid)

            steps.append(self._serialize_step(funnel_step, relevant_people))

        if len(steps) > 0:
            for index, _ in enumerate(steps):
                steps[index]["people"] = sorted(steps[index]["people"], key=lambda p: person_score[p], reverse=True)[
                    0:100
                ]

        return steps

    def run(self, *args, **kwargs) -> List[Dict[str, Any]]:
        results = self._exec_query()
        if len(results) == 0:
            return self.data_to_return([])
        width = len(results[0])  # the three
        res = []
        for result_tuple in results:
            result = list(result_tuple)
            person = Person(pk=result[0], uuid=result[0])
            person.max_step = result[1]
            res.append(person)
        return self.data_to_return(res)
