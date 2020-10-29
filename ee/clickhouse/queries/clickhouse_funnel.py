import uuid
from collections import defaultdict
from typing import Any, Dict, List, Match, Tuple

from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.funnels.funnel import FUNNEL_SQL
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

    def __init__(self, filter: Filter, team: Team) -> None:
        self._filter = filter
        self._team = team

    def _build_filters(self, entity: Entity, index: int) -> str:
        prop_filters, prop_filter_params = parse_prop_clauses(
            "uuid", entity.properties, self._team, prepend=str(index), json_extract=True
        )
        self.params.update(prop_filter_params)
        if entity.properties:
            return prop_filters
        return ""

    def _build_steps_query(self, entity: Entity, index: int) -> str:
        filters = self._build_filters(entity, index)
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=entity.id)
            action_query, action_params = format_action_filter(action, "step_{}".format(index))
            if action_query == "":
                return ""

            self.params.update(action_params)
            content_sql = "uuid IN {actions_query} {filters}".format(actions_query=action_query, filters=filters,)
        else:
            content_sql = "event = '{event}' {filters}".format(event=entity.id, filters=filters)
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
            team_id=self._team.id,
            steps=", ".join(steps),
            filters=prop_filters.replace("uuid IN", "events.uuid IN", 1),
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
        )
        return sync_execute(query, self.params)

    def _data_to_return(self, results: List[Dict]) -> List[Dict[str, Any]]:
        steps = []
        person_score: Dict = defaultdict(int)
        for index, funnel_step in enumerate(self._filter.entities):
            relevant_people = []
            for person in results:
                if index < person["max_step"]:
                    person_score[person["uuid"]] += 1
                    relevant_people.append(person["uuid"])

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
            return self._data_to_return([])
        width = len(results[0])  # the three
        res = []
        for result_tuple in results:
            result = list(result_tuple)
            res.append({"uuid": result[0], "max_step": result[1]})
        return self._data_to_return(res)
