from collections import namedtuple
from typing import Any, Dict, List

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import parse_timestamps
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filter import Filter
from posthog.models.team import Team
from posthog.queries.funnel import Funnel

FUNNEL_SQL = """
    SELECT 
        person_distinct_id.person_id as id,
        groupArray(events.timestamp) as timestamps,
        groupArray(events.event) as eventsArr,
        groupArray(events.id) as event_ids,
        {steps}
    FROM events 
    JOIN person_distinct_id ON person_distinct_id.distinct_id = events.distinct_id
    WHERE team_id = {team_id} {date_from} {date_to}
    GROUP BY
    person_distinct_id.person_id, team_id
"""
# STEP_ACTION_SQL = """
#     arrayFilter(time -> {is_first_step}, groupArrayIf(timestamp, team_id = {team_id} AND id IN ({actions_query}) {filters} {parsed_date_from} {parsed_date_to}) )[1] AS step_{step}
# """

# STEP_EVENT_SQL = """
#     arrayFilter(time -> {is_first_step}, groupArrayIf(timestamp, team_id = {team_id} AND event = '{event}' {filters} {parsed_date_from} {parsed_date_to}) )[1] AS step_{step}
# """

STEP_ACTION_SQL = """
    arrayFilter((timestamp, event, random_event_id) -> {is_first_step} AND (team_id = {team_id}) AND random_event_id IN ({actions_query}) {filters} {parsed_date_from} {parsed_date_to}
        , timestamps, eventsArr, event_ids )[1] AS step_{step}
"""

STEP_EVENT_SQL = """
    arrayFilter((timestamp, event, random_event_id) -> {is_first_step} AND (team_id = {team_id}) AND event = '{event}' {filters}
        , timestamps, eventsArr, event_ids )[1] AS step_{step}
"""


class ClickhouseFunnel(Funnel):
    _filter: Filter
    _team: Team

    def __init__(self, filter: Filter, team: Team) -> None:
        self._filter = filter
        self._team = team

    def _build_steps_query(self, entity: Entity, index: int) -> str:
        parsed_date_from, parsed_date_to = parse_timestamps(filter=self._filter)
        prop_filters, prop_filter_params = parse_prop_clauses("id", entity.properties, self._team, prepend=index)
        is_first_step = (
            "timestamp <> toDateTime(0)"
            if index == 0
            else "timestamp <> toDateTime(0) AND timestamp >= step_{prev_step}".format(prev_step=index - 1)
        )
        self.params.update(prop_filter_params)
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=entity.id)
            action_query, action_params = format_action_filter(action)
            if action_query == "":
                return None

            self.params.update(action_params)
            content_sql = STEP_ACTION_SQL.format(
                team_id=self._team.pk,
                actions_query=action_query,
                parsed_date_from=(parsed_date_from or ""),
                parsed_date_to=(parsed_date_to or ""),
                filters="{filters}".format(filters=prop_filters.replace("id IN", "random_event_id IN", 1))
                if entity.properties
                else "",
                step=index,
                is_first_step=is_first_step,
            )
        else:
            content_sql = STEP_EVENT_SQL.format(
                team_id=self._team.pk,
                event=entity.id,
                parsed_date_from=(parsed_date_from or ""),
                parsed_date_to=(parsed_date_to or ""),
                filters="{filters}".format(filters=prop_filters.replace("id IN", "random_event_id IN", 1))
                if entity.properties
                else "",
                step=index,
                is_first_step=is_first_step,
            )
        return content_sql

    def _exec_query(self) -> str:
        parsed_date_from, parsed_date_to = parse_timestamps(filter=self._filter)
        prop_filters, prop_filter_params = parse_prop_clauses("id", self._filter.properties, self._team)
        self.params: Dict = {"team_id": self._team.pk}
        steps = [self._build_steps_query(entity, index) for index, entity in enumerate(self._filter.entities)]
        query = FUNNEL_SQL.format(
            date_from=parsed_date_from, date_to=parsed_date_to, team_id=self._team.id, steps=", ".join(steps)
        )
        print(query)
        print("==")
        print(self.params)
        print("------")
        return sync_execute(query, self.params)

    def run(self, *args, **kwargs) -> List[Dict[str, Any]]:
        results = self._exec_query()
        if len(results) == 0:
            return []
        width = len(results[0]) - 3  # the three
        res = []
        for result in results:
            result = list(result)
            del result[1:4]
            if result[1].year == 1970:
                continue
            person = namedtuple("Person", "id")
            person.pk = result[0]
            person.id = result[0]
            for step in range(0, width - 1):
                setattr(person, "step_{}".format(step), result[step + 1] if result[step + 1].year != 1970 else None)
            res.append(person)
        return self.data_to_return(res)
