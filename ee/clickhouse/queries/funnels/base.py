from abc import ABC, abstractmethod
from typing import List, Tuple

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.breakdown_props import get_breakdown_event_prop_values, get_breakdown_person_prop_values
from ee.clickhouse.queries.funnels.funnel_event_query import FunnelEventQuery
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.funnels.funnel import FUNNEL_INNER_EVENT_STEPS_QUERY
from ee.clickhouse.sql.person import GET_LATEST_PERSON_DISTINCT_ID_SQL
from posthog.constants import FUNNEL_WINDOW_DAYS, TREND_FILTER_TYPE_ACTIONS
from posthog.models import Action, Entity, Filter, Team
from posthog.models.filters.mixins.funnel import FunnelWindowDaysMixin
from posthog.queries.funnel import Funnel
from posthog.utils import relative_date_parse


class ClickhouseFunnelBase(ABC, Funnel):
    _filter: Filter
    _team: Team

    def __init__(self, filter: Filter, team: Team) -> None:
        self._filter = filter

        # handle default if window isn't provided
        if not self._filter.funnel_window_days:
            self._filter = self._filter.with_data({FUNNEL_WINDOW_DAYS: 14})

        self._team = team
        self.params = {
            "team_id": self._team.pk,
            "events": [],  # purely a speed optimization, don't need this for filtering
        }

    def run(self, *args, **kwargs):
        if len(self._filter.entities) == 0:
            return []

        results = self._exec_query()
        return self._format_results(results)

    def _format_results(self, results):
        # Format of this is [step order, person count (that reached that step), array of person uuids]
        steps = []
        total_people = 0

        for step in reversed(self._filter.entities):

            if results[0] and len(results[0]) > 0:
                total_people += results[0][step.order]

            serialized_result = self._serialize_step(step, total_people, [])
            if step.order > 0:
                serialized_result.update(
                    {"average_conversion_time": results[0][step.order + len(self._filter.entities) - 1]}
                )
            else:
                serialized_result.update({"average_conversion_time": None})
            steps.append(serialized_result)

        return steps[::-1]  #  reverse

    def _exec_query(self) -> List[Tuple]:

        # format default dates
        data = {}
        if not self._filter._date_from:
            data.update({"date_from": relative_date_parse("-7d")})
        if not self._filter._date_to:
            data.update({"date_to": timezone.now()})
        self._filter = self._filter.with_data(data)

        query = self.get_query()

        return sync_execute(query, self.params)

    def _get_step_times(self, max_steps: int):
        conditions: List[str] = []
        for i in range(1, max_steps):
            conditions.append(
                f"if(isNotNull(latest_{i}), dateDiff('second', toDateTime(latest_{i - 1}), toDateTime(latest_{i})), NULL) step_{i}_average_conversion_time"
            )

        formatted = ", ".join(conditions)
        return f", {formatted}" if formatted else ""

    def _get_partition_cols(self, level_index: int, max_steps: int):
        cols: List[str] = []
        for i in range(0, max_steps):
            cols.append(f"step_{i}")
            if i < level_index:
                cols.append(f"latest_{i}")
            else:
                duplicate_event = 0
                if i > 0 and self._filter.entities[i].equals(self._filter.entities[i - 1]):
                    duplicate_event = 1
                cols.append(
                    f"min(latest_{i}) over (PARTITION by person_id ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND {duplicate_event} PRECEDING) latest_{i}"
                )
        return ", ".join(cols)

    def _get_comparison_at_step(self, index: int, level_index: int):
        or_statements: List[str] = []

        for i in range(level_index, index + 1):
            or_statements.append(f"latest_{i} < latest_{level_index - 1}")

        return " OR ".join(or_statements)

    def _get_sorting_condition(self, curr_index: int, max_steps: int):

        if curr_index == 1:
            return "1"

        conditions: List[str] = []
        for i in range(1, curr_index):
            conditions.append(f"latest_{i - 1} < latest_{i }")
            conditions.append(f"latest_{i} <= latest_0 + INTERVAL {self._filter.funnel_window_days} DAY")

        return f"if({' AND '.join(conditions)}, {curr_index}, {self._get_sorting_condition(curr_index - 1, max_steps)})"

    def _get_inner_event_query(
        self, entities=None, entity_name="events", skip_entity_filter=False, skip_step_filter=False
    ) -> str:
        entities_to_use = entities or self._filter.entities

        event_query, params = FunnelEventQuery(filter=self._filter, team_id=self._team.pk).get_query(
            entities_to_use, entity_name, skip_entity_filter=skip_entity_filter
        )

        self.params.update(params)

        if skip_step_filter:
            steps_conditions = "1=1"
        else:
            steps_conditions = self._get_steps_conditions(length=len(self._filter.entities))

        all_step_cols: List[str] = []
        for index, entity in enumerate(entities_to_use):
            step_cols = self._get_step_col(entity, index, entity_name)
            all_step_cols.extend(step_cols)

        steps = ", ".join(all_step_cols)

        select_prop = self._get_breakdown_select_prop()
        breakdown_conditions = self._get_breakdown_conditions()
        extra_conditions = "AND prop != ''" if select_prop else ""
        extra_conditions += f"AND {breakdown_conditions}" if breakdown_conditions and select_prop else ""

        return FUNNEL_INNER_EVENT_STEPS_QUERY.format(
            steps=steps,
            event_query=event_query,
            steps_condition=steps_conditions,
            select_prop=select_prop,
            extra_conditions=extra_conditions,
        )

    def _get_steps_conditions(self, length: int) -> str:
        step_conditions: List[str] = []

        for index in range(length):
            step_conditions.append(f"step_{index} = 1")

        return " OR ".join(step_conditions)

    def _get_step_col(self, entity: Entity, index: int, entity_name: str) -> List[str]:
        step_cols: List[str] = []
        condition = self._build_step_query(entity, index, entity_name)
        step_cols.append(f"if({condition}, 1, 0) as step_{index}")
        step_cols.append(f"if(step_{index} = 1, timestamp, null) as latest_{index}")

        return step_cols

    def _build_step_query(self, entity: Entity, index: int, entity_name: str) -> str:
        filters = self._build_filters(entity, index)
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=entity.id)
            for action_step in action.steps.all():
                self.params[entity_name].append(action_step.event)
            action_query, action_params = format_action_filter(action, "{}_step_{}".format(entity_name, index))
            if action_query == "":
                return ""

            self.params.update(action_params)
            content_sql = "{actions_query} {filters}".format(actions_query=action_query, filters=filters,)
        else:
            self.params[entity_name].append(entity.id)
            event_param_key = f"{entity_name}_event_{index}"
            self.params[event_param_key] = entity.id
            content_sql = f"event = %({event_param_key})s {filters}"
        return content_sql

    def _build_filters(self, entity: Entity, index: int) -> str:
        prop_filters, prop_filter_params = parse_prop_clauses(
            entity.properties, self._team.pk, prepend=str(index), allow_denormalized_props=True
        )
        self.params.update(prop_filter_params)
        if entity.properties:
            return prop_filters
        return ""

    def _get_funnel_person_step_condition(self):
        step_num = self._filter.funnel_step
        max_steps = len(self._filter.entities)

        if step_num is None:
            raise ValueError("funnel_step should not be none")

        if step_num >= 0:
            self.params.update({"step_num": [i for i in range(step_num, max_steps + 1)]})
            return "steps IN %(step_num)s"
        else:
            self.params.update({"step_num": abs(step_num) - 1})
            return "steps = %(step_num)s"

    def _get_count_columns(self, max_steps: int):
        cols: List[str] = []

        for i in range(max_steps):
            cols.append(f"countIf(steps = {i + 1}) step_{i + 1}")

        return ", ".join(cols)

    def _get_step_time_avgs(self, max_steps: int):
        conditions: List[str] = []
        for i in range(1, max_steps):
            conditions.append(f"avg(step_{i}_average_conversion_time) step_{i}_average_conversion_time")

        formatted = ", ".join(conditions)
        return f", {formatted}" if formatted else ""

    @abstractmethod
    def get_query(self):
        pass

    def get_step_counts_query(self):
        pass

    def get_step_counts_without_aggregation_query(self):
        pass

    def _get_breakdown_select_prop(self) -> str:
        if self._filter.breakdown:
            self.params.update({"breakdown": self._filter.breakdown})
            if self._filter.breakdown_type == "person":
                return f", JSONExtractRaw(person_props, %(breakdown)s) as prop"
            elif self._filter.breakdown_type == "event":
                return f", JSONExtractRaw(properties, %(breakdown)s) as prop"

        return ""

    def _get_breakdown_conditions(self) -> str:
        if self._filter.breakdown:
            limit = 5
            first_entity = next(x for x in self._filter.entities if x.order == 0)
            if not first_entity:
                ValidationError("An entity with order 0 was not provided")
            values = []
            if self._filter.breakdown_type == "person":
                values = get_breakdown_person_prop_values(self._filter, first_entity, "count(*)", self._team.pk, 5)
            elif self._filter.breakdown_type == "event":
                values = get_breakdown_event_prop_values(self._filter, first_entity, "count(*)", self._team.pk, 5)
            self.params.update({"breakdown_values": values})

            return "prop IN %(breakdown_values)s"
        else:
            return ""

    def _get_breakdown_prop(self) -> str:
        if self._filter.breakdown:
            return ", prop"
        else:
            return ""
