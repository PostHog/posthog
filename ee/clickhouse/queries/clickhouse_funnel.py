from collections import namedtuple
from typing import Any, Dict, List, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import parse_timestamps
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filter import Filter
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.queries.funnel import Funnel

FUNNEL_SQL = """
SELECT id, {select_steps} FROM (
    SELECT 
        person_distinct_id.person_id as id,
        groupArray(events.timestamp) as timestamps,
        groupArray(events.event) as eventsArr,
        groupArray(events.uuid) as event_ids,
        {steps}
    FROM events 
    JOIN person_distinct_id ON person_distinct_id.distinct_id = events.distinct_id
    WHERE team_id = {team_id} {filters} {parsed_date_from} {parsed_date_to}
    GROUP BY person_distinct_id.person_id, team_id
    ORDER BY timestamps
 ) WHERE step_0 <> toDateTime(0)
"""

STEP_ACTION_SQL = """
    arrayFilter(
        (timestamp, event, random_event_id) ->
            {is_first_step} AND
            (team_id = {team_id}) AND
            random_event_id IN ({actions_query}) {filters}
        , timestamps, eventsArr, event_ids
    )[1] AS step_{step}
"""

STEP_EVENT_SQL = """
    arrayFilter(
        (timestamp, event, random_event_id) ->
            {is_first_step} AND
            (team_id = {team_id}) AND
            event = '{event}' {filters} 
        , timestamps, eventsArr, event_ids
    )[1] AS step_{step}
"""


class ClickhouseFunnel(Funnel):
    _filter: Filter
    _team: Team

    def __init__(self, filter: Filter, team: Team) -> None:
        self._filter = filter
        self._team = team

    def _build_filters(self, entity: Entity, index: int) -> str:
        prop_filters, prop_filter_params = parse_prop_clauses("uuid", entity.properties, self._team, prepend=str(index))
        self.params.update(prop_filter_params)
        if entity.properties:
            return prop_filters.replace("uuid IN", "random_event_id IN", 1)
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
            content_sql = STEP_ACTION_SQL.format(
                team_id=self._team.pk,
                actions_query=action_query,
                parsed_date_from=(parsed_date_from or ""),
                parsed_date_to=(parsed_date_to or ""),
                filters=filters,
                step=index,
                is_first_step=is_first_step,
            )
        else:
            content_sql = STEP_EVENT_SQL.format(
                team_id=self._team.pk,
                event=entity.id,
                parsed_date_from=(parsed_date_from or ""),
                parsed_date_to=(parsed_date_to or ""),
                filters=filters,
                step=index,
                is_first_step=is_first_step,
            )
        return content_sql

    def _exec_query(self) -> List[Tuple]:
        prop_filters, prop_filter_params = parse_prop_clauses(
            "uuid", self._filter.properties, self._team, prepend="global"
        )
        parsed_date_from, parsed_date_to = parse_timestamps(filter=self._filter)
        self.params: Dict = {"team_id": self._team.pk, **prop_filter_params}
        steps = [self._build_steps_query(entity, index) for index, entity in enumerate(self._filter.entities)]
        query = FUNNEL_SQL.format(
            select_steps=",".join(["step_{}".format(index) for index, _ in enumerate(self._filter.entities)]),
            team_id=self._team.id,
            steps=", ".join(steps),
            filters=prop_filters.replace("uuid IN", "events.uuid IN", 1),
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
        )
        return sync_execute(query, self.params)

    def run(self, *args, **kwargs) -> List[Dict[str, Any]]:
        results = self._exec_query()
        if len(results) == 0:
            return []
        width = len(results[0])  # the three
        res = []
        for result_tuple in results:
            result = list(result_tuple)
            person = Person(pk=result[0])
            for step in range(0, width - 1):
                setattr(person, "step_{}".format(step), result[step + 1] if result[step + 1].year != 1970 else None)
            res.append(person)
        return self.data_to_return(res)
