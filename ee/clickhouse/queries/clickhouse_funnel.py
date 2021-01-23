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
from posthog.models.filters import Filter
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
            entity.properties, self._team.pk, prepend=str(index), allow_denormalized_props=True
        )
        self.params.update(prop_filter_params)
        if entity.properties:
            return prop_filters
        return ""

    def _build_steps_query(self, entity: Entity, index: int) -> str:
        filters = self._build_filters(entity, index)
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=entity.id)
            for action_step in action.steps.all():
                self.params["events"].append(action_step.event)
            action_query, action_params = format_action_filter(action, "step_{}".format(index))
            if action_query == "":
                return ""

            self.params.update(action_params)
            content_sql = "{actions_query} {filters}".format(actions_query=action_query, filters=filters,)
        else:
            self.params["events"].append(entity.id)
            content_sql = "event = '{event}' {filters}".format(event=entity.id, filters=filters)
        return content_sql

    def _exec_query(self) -> List[Tuple]:
        prop_filters, prop_filter_params = parse_prop_clauses(
            self._filter.properties, self._team.pk, prepend="global", allow_denormalized_props=True
        )

        # format default dates
        data = {}
        if not self._filter._date_from:
            data.update({"date_from": relative_date_parse("-7d")})
        if not self._filter._date_to:
            data.update({"date_to": timezone.now()})
        self._filter = Filter(data={**self._filter._data, **data})

        parsed_date_from, parsed_date_to, _ = parse_timestamps(
            filter=self._filter, table="events.", team_id=self._team.pk
        )
        self.params: Dict = {
            "team_id": self._team.pk,
            "events": [],  # purely a speed optimization, don't need this for filtering
            **prop_filter_params,
        }
        steps = [self._build_steps_query(entity, index) for index, entity in enumerate(self._filter.entities)]
        query = FUNNEL_SQL.format(
            team_id=self._team.id,
            steps=", ".join(steps),
            filters=prop_filters.replace("uuid IN", "events.uuid IN", 1),
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
        )
        return sync_execute(query, self.params)

    def run(self, *args, **kwargs) -> List[Dict[str, Any]]:
        # Format of this is [step order, person count (that reached that step), array of person uuids]
        results = self._exec_query()

        steps = []
        relevant_people = []
        total_people = 0

        for step in reversed(self._filter.entities):
            # Clickhouse step order starts at one, hence the +1
            result_step = [x for x in results if step.order + 1 == x[0]]
            if len(result_step) > 0:
                total_people += result_step[0][1]
                relevant_people += result_step[0][2]
            steps.append(self._serialize_step(step, total_people, relevant_people[0:100]))

        return steps[::-1]  #  reverse
