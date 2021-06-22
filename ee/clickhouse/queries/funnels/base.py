from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple

from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.funnels.funnel_event_query import FunnelEventQuery
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.funnels.funnel import FUNNEL_INNER_EVENT_STEPS_QUERY
from ee.clickhouse.sql.person import GET_LATEST_PERSON_DISTINCT_ID_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models import Action, Entity, Filter, Team
from posthog.models.filters.mixins.funnel_window_days import FunnelWindowDaysMixin
from posthog.queries.funnel import Funnel
from posthog.utils import relative_date_parse


class ClickhouseFunnelBase(ABC, Funnel):
    _filter: Filter
    _team: Team

    def __init__(self, filter: Filter, team: Team) -> None:
        self._filter = filter
        self._team = team
        self.params = {
            "team_id": self._team.pk,
            "events": [],  # purely a speed optimization, don't need this for filtering
        }

    def run(self, *args, **kwargs):
        if len(self._filter.entities) == 0:
            return []

        # if self._filter.display == TRENDS_LINEAR:
        #     return ClickhouseFunnelTrends(self._filter, self._team).run()
        # else:

        # Format of this is [step order, person count (that reached that step), array of person uuids]
        results = self._exec_query()

        if self._filter.offset > 0:
            return results

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

    def _exec_query(self) -> List[Tuple]:
        prop_filters, prop_filter_params = parse_prop_clauses(
            self._filter.properties,
            self._team.pk,
            prepend="global",
            allow_denormalized_props=True,
            filter_test_accounts=self._filter.filter_test_accounts,
        )

        # format default dates
        data = {}
        if not self._filter._date_from:
            data.update({"date_from": relative_date_parse("-7d")})
        if not self._filter._date_to:
            data.update({"date_to": timezone.now()})
        self._filter = self._filter.with_data(data)

        parsed_date_from, parsed_date_to, _ = parse_timestamps(
            filter=self._filter, table="events.", team_id=self._team.pk
        )
        self.params.update(prop_filter_params)
        steps = [self._build_step_query(entity, index) for index, entity in enumerate(self._filter.entities)]

        format_properties = {
            "team_id": self._team.id,
            "steps": ", ".join(steps),
            "filters": prop_filters.replace("uuid IN", "events.uuid IN", 1),
            "parsed_date_from": parsed_date_from,
            "parsed_date_to": parsed_date_to,
            "top_level_groupby": "",
            "extra_select": "",
            "extra_groupby": "",
            "within_time": FunnelWindowDaysMixin.microseconds_from_days(self._filter.funnel_window_days),
            "latest_distinct_id_sql": GET_LATEST_PERSON_DISTINCT_ID_SQL,
            "offset": self._filter.offset,
        }

        query = self.get_query(format_properties)

        return sync_execute(query, self.params)

    def _get_inner_event_query(self) -> Tuple[str, Dict[str, Any]]:
        event_query, params = FunnelEventQuery(filter=self._filter, team_id=self._team.pk).get_query()
        self.params.update(params)
        steps_conditions = self._get_steps_conditions(length=len(self._filter.entities))

        all_step_cols: List[str] = []
        for index, entity in enumerate(self._filter.entities):
            step_cols = self._get_step_col(entity, index)
            all_step_cols = [*all_step_cols, *step_cols]

        steps = ", ".join(all_step_cols)

        select_prop = self._get_select_prop()

        return FUNNEL_INNER_EVENT_STEPS_QUERY.format(
            steps=steps,
            event_query=event_query,
            steps_condition=steps_conditions,
            select_prop=select_prop,
            extra_conditions=("AND prop != ''" if select_prop else ""),
        )

    def _get_select_prop(self) -> str:
        if self._filter.breakdown:
            self.params.update({"breakdown": self._filter.breakdown})
            if self._filter.breakdown_type == "person":
                return f", trim(BOTH '\"' FROM JSONExtractRaw(person_props, %(breakdown)s)) as prop"
            elif self._filter.breakdown_type == "event":
                return f", trim(BOTH '\"' FROM JSONExtractRaw(properties, %(breakdown)s)) as prop"
        else:
            return ""

    def _get_steps_conditions(self, length: int) -> str:
        step_conditions: List[str] = []

        for index in range(length):
            step_conditions.append(f"step_{index} = 1")

        return " OR ".join(step_conditions)

    def _get_step_col(self, entity: Entity, index: int) -> List[str]:
        step_cols: List[str] = []
        condition = self._build_step_query(entity, index)
        step_cols.append(f"if({condition}, 1, 0) as step_{index}")
        step_cols.append(f"if(step_{index} = 1, timestamp, null) as latest_{index}")

        return step_cols

    def _build_step_query(self, entity: Entity, index: int) -> str:
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
            self.params[f"event_{index}"] = entity.id
            content_sql = f"event = %(event_{index})s {filters}"
        return content_sql

    def _build_filters(self, entity: Entity, index: int) -> str:
        prop_filters, prop_filter_params = parse_prop_clauses(
            entity.properties, self._team.pk, prepend=str(index), allow_denormalized_props=True
        )
        self.params.update(prop_filter_params)
        if entity.properties:
            return prop_filters
        return ""

    @abstractmethod
    def get_query(self, format_properties):
        pass
