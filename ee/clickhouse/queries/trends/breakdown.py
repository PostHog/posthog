import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from ee.clickhouse.models.property import get_property_string_expr, parse_prop_grouped_clauses
from ee.clickhouse.queries.breakdown_props import (
    ALL_USERS_COHORT_ID,
    format_breakdown_cohort_join_query,
    get_breakdown_cohort_name,
    get_breakdown_prop_values,
)
from ee.clickhouse.queries.column_optimizer import EnterpriseColumnOptimizer
from ee.clickhouse.queries.groups_join_query import GroupsJoinQuery
from ee.clickhouse.queries.trends.util import enumerate_time_range, get_active_user_params, parse_response, process_math
from ee.clickhouse.sql.events import EVENT_JOIN_PERSON_SQL
from ee.clickhouse.sql.trends.breakdown import (
    BREAKDOWN_ACTIVE_USER_CONDITIONS_SQL,
    BREAKDOWN_ACTIVE_USER_INNER_SQL,
    BREAKDOWN_AGGREGATE_QUERY_SQL,
    BREAKDOWN_COHORT_JOIN_SQL,
    BREAKDOWN_CUMULATIVE_INNER_SQL,
    BREAKDOWN_INNER_SQL,
    BREAKDOWN_PROP_JOIN_SQL,
    BREAKDOWN_QUERY_SQL,
)
from posthog.constants import (
    MONTHLY_ACTIVE,
    NON_TIME_SERIES_DISPLAY_TYPES,
    TREND_FILTER_TYPE_ACTIONS,
    TRENDS_CUMULATIVE,
    WEEKLY_ACTIVE,
    PropertyOperatorType,
)
from posthog.models.action.util import format_action_filter
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.team import Team
from posthog.models.utils import PersonPropertiesMode
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query
from posthog.queries.person_query import PersonQuery
from posthog.queries.util import date_from_clause, get_time_diff, get_trunc_func_ch, parse_timestamps, start_of_week_fix
from posthog.utils import encode_get_request_params


class ClickhouseTrendsBreakdown:
    DISTINCT_ID_TABLE_ALIAS = "pdi"

    def __init__(
        self, entity: Entity, filter: Filter, team: Team, column_optimizer: Optional[EnterpriseColumnOptimizer] = None
    ):
        self.entity = entity
        self.filter = filter
        self.team = team
        self.team_id = team.pk
        self.params: Dict[str, Any] = {"team_id": team.pk}
        self.column_optimizer = column_optimizer or EnterpriseColumnOptimizer(self.filter, self.team_id)

    def get_query(self) -> Tuple[str, Dict, Callable]:
        interval_annotation = get_trunc_func_ch(self.filter.interval)
        num_intervals, seconds_in_interval, round_interval = get_time_diff(
            self.filter.interval, self.filter.date_from, self.filter.date_to, self.team_id
        )
        _, parsed_date_to, date_params = parse_timestamps(filter=self.filter, team=self.team)

        props_to_filter = self.filter.property_groups.combine_property_group(
            PropertyOperatorType.AND, self.entity.property_groups
        )

        outer_properties = self.column_optimizer.property_optimizer.parse_property_groups(props_to_filter).outer
        prop_filters, prop_filter_params = parse_prop_grouped_clauses(
            team_id=self.team_id,
            property_group=outer_properties,
            table_name="e",
            person_properties_mode=PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
            person_id_joined_alias=f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id",
        )
        aggregate_operation, _, math_params = process_math(
            self.entity, self.team, event_table_alias="e", person_id_alias=f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id"
        )

        action_query = ""
        action_params: Dict = {}
        if self.entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = self.entity.get_action()
            action_query, action_params = format_action_filter(team_id=self.team_id, action=action, table_name="e")

        self.params = {
            **self.params,
            **math_params,
            **prop_filter_params,
            **action_params,
            "event": self.entity.id,
            "key": self.filter.breakdown,
            **date_params,
            "timezone": self.team.timezone_for_charts,
        }

        breakdown_filter_params = {
            "parsed_date_from": date_from_clause(interval_annotation, round_interval),
            "parsed_date_to": parsed_date_to,
            "actions_query": "AND {}".format(action_query) if action_query else "",
            "event_filter": "AND event = %(event)s" if not action_query else "",
            "filters": prop_filters if props_to_filter.values else "",
        }

        _params, _breakdown_filter_params = {}, {}

        if self.filter.breakdown_type == "cohort":
            _params, breakdown_filter, _breakdown_filter_params, breakdown_value = self._breakdown_cohort_params()
        else:
            _params, breakdown_filter, _breakdown_filter_params, breakdown_value = self._breakdown_prop_params(
                "count(*)" if self.entity.math == "dau" else aggregate_operation, math_params,
            )

        if len(_params["values"]) == 0:
            # If there are no breakdown values, we are sure that there's no relevant events, so instead of adjusting
            # a "real" SELECT for this, we only include the below dummy SELECT.
            # It's a drop-in replacement for a "real" one, simply always returning 0 rows.
            # See https://github.com/PostHog/posthog/pull/5674 for context.
            return (
                "SELECT [now()] AS date, [0] AS data, '' AS breakdown_value LIMIT 0",
                {},
                lambda _: [],
            )

        person_join_condition, person_join_params = self._person_join_condition()
        groups_join_condition, groups_join_params = GroupsJoinQuery(
            self.filter, self.team_id, self.column_optimizer
        ).get_join_query()
        self.params = {**self.params, **_params, **person_join_params, **groups_join_params}
        breakdown_filter_params = {**breakdown_filter_params, **_breakdown_filter_params}

        if self.filter.display in NON_TIME_SERIES_DISPLAY_TYPES:
            breakdown_filter = breakdown_filter.format(**breakdown_filter_params)
            content_sql = BREAKDOWN_AGGREGATE_QUERY_SQL.format(
                breakdown_filter=breakdown_filter,
                person_join=person_join_condition,
                groups_join=groups_join_condition,
                aggregate_operation=aggregate_operation,
                breakdown_value=breakdown_value,
            )
            time_range = enumerate_time_range(self.filter, seconds_in_interval)

            return (
                content_sql,
                self.params,
                self._parse_single_aggregate_result(self.filter, self.entity, {"days": time_range}),
            )

        else:

            breakdown_filter = breakdown_filter.format(**breakdown_filter_params)

            if self.entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
                active_user_params = get_active_user_params(self.filter, self.entity, self.team_id)
                conditions = BREAKDOWN_ACTIVE_USER_CONDITIONS_SQL.format(
                    **breakdown_filter_params, **active_user_params
                )
                inner_sql = BREAKDOWN_ACTIVE_USER_INNER_SQL.format(
                    breakdown_filter=breakdown_filter,
                    person_join=person_join_condition,
                    groups_join=groups_join_condition,
                    aggregate_operation=aggregate_operation,
                    interval_annotation=interval_annotation,
                    breakdown_value=breakdown_value,
                    conditions=conditions,
                    GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(self.team_id),
                    **active_user_params,
                    **breakdown_filter_params,
                )
            elif self.filter.display == TRENDS_CUMULATIVE and self.entity.math == "dau":
                inner_sql = BREAKDOWN_CUMULATIVE_INNER_SQL.format(
                    breakdown_filter=breakdown_filter,
                    person_join=person_join_condition,
                    groups_join=groups_join_condition,
                    aggregate_operation=aggregate_operation,
                    interval_annotation=interval_annotation,
                    breakdown_value=breakdown_value,
                    start_of_week_fix=start_of_week_fix(self.filter),
                    **breakdown_filter_params,
                )
            else:
                inner_sql = BREAKDOWN_INNER_SQL.format(
                    breakdown_filter=breakdown_filter,
                    person_join=person_join_condition,
                    groups_join=groups_join_condition,
                    aggregate_operation=aggregate_operation,
                    interval_annotation=interval_annotation,
                    breakdown_value=breakdown_value,
                    start_of_week_fix=start_of_week_fix(self.filter),
                )

            breakdown_query = BREAKDOWN_QUERY_SQL.format(
                interval=interval_annotation, num_intervals=num_intervals, inner_sql=inner_sql,
            )
            self.params.update(
                {"seconds_in_interval": seconds_in_interval, "num_intervals": num_intervals,}
            )

            return breakdown_query, self.params, self._parse_trend_result(self.filter, self.entity)

    def _breakdown_cohort_params(self):
        cohort_queries, cohort_ids, cohort_params = format_breakdown_cohort_join_query(
            self.team, self.filter, entity=self.entity
        )
        params = {"values": cohort_ids, **cohort_params}
        breakdown_filter = BREAKDOWN_COHORT_JOIN_SQL
        breakdown_filter_params = {"cohort_queries": cohort_queries}

        return params, breakdown_filter, breakdown_filter_params, "value"

    def _breakdown_prop_params(self, aggregate_operation: str, math_params: Dict):
        values_arr = get_breakdown_prop_values(
            self.filter,
            self.entity,
            aggregate_operation,
            self.team,
            extra_params=math_params,
            column_optimizer=self.column_optimizer,
        )

        # :TRICKY: We only support string breakdown for event/person properties
        assert isinstance(self.filter.breakdown, str)

        if self.filter.breakdown_type == "person":
            breakdown_value, _ = get_property_string_expr("person", self.filter.breakdown, "%(key)s", "person_props")
        elif self.filter.breakdown_type == "group":
            properties_field = f"group_properties_{self.filter.breakdown_group_type_index}"
            breakdown_value, _ = get_property_string_expr("groups", self.filter.breakdown, "%(key)s", properties_field)
        else:
            breakdown_value, _ = get_property_string_expr("events", self.filter.breakdown, "%(key)s", "properties")

        return (
            {"values": values_arr},
            BREAKDOWN_PROP_JOIN_SQL,
            {"breakdown_value_expr": breakdown_value},
            breakdown_value,
        )

    def _parse_single_aggregate_result(
        self, filter: Filter, entity: Entity, additional_values: Dict[str, Any]
    ) -> Callable:
        def _parse(result: List) -> List:
            parsed_results = []
            for idx, stats in enumerate(result):
                result_descriptors = self._breakdown_result_descriptors(stats[1], filter, entity)
                filter_params = filter.to_params()
                extra_params = {
                    "entity_id": entity.id,
                    "entity_type": entity.type,
                    "breakdown_value": result_descriptors["breakdown_value"],
                    "breakdown_type": filter.breakdown_type or "event",
                }
                parsed_params: Dict[str, str] = encode_get_request_params({**filter_params, **extra_params})
                parsed_result = {
                    "aggregated_value": stats[0],
                    "filter": filter_params,
                    "persons": {
                        "filter": extra_params,
                        "url": f"api/projects/{self.team_id}/actions/people/?{urllib.parse.urlencode(parsed_params)}",
                    },
                    **result_descriptors,
                    **additional_values,
                }
                parsed_results.append(parsed_result)

            return parsed_results

        return _parse

    def _parse_trend_result(self, filter: Filter, entity: Entity) -> Callable:
        def _parse(result: List) -> List:
            parsed_results = []
            for idx, stats in enumerate(result):
                result_descriptors = self._breakdown_result_descriptors(stats[2], filter, entity)
                parsed_result = parse_response(stats, filter, additional_values=result_descriptors)
                parsed_result.update(
                    {
                        "persons_urls": self._get_persons_url(
                            filter, entity, self.team_id, parsed_result["days"], result_descriptors["breakdown_value"]
                        )
                    }
                )
                parsed_results.append(parsed_result)
                parsed_result.update({"filter": filter.to_dict()})
            return sorted(parsed_results, key=lambda x: 0 if x.get("breakdown_value") != "all" else 1)

        return _parse

    def _get_persons_url(
        self, filter: Filter, entity: Entity, team_id: int, dates: List[str], breakdown_value: Union[str, int]
    ) -> List[Dict[str, Any]]:
        persons_url = []
        for date in dates:
            filter_params = filter.to_params()
            extra_params = {
                "entity_id": entity.id,
                "entity_type": entity.type,
                "entity_math": entity.math,
                "date_from": filter.date_from if filter.display == TRENDS_CUMULATIVE else date,
                "date_to": date,
                "breakdown_value": breakdown_value,
                "breakdown_type": filter.breakdown_type or "event",
            }
            parsed_params: Dict[str, str] = encode_get_request_params({**filter_params, **extra_params})
            persons_url.append(
                {
                    "filter": extra_params,
                    "url": f"api/projects/{team_id}/actions/people/?{urllib.parse.urlencode(parsed_params)}",
                }
            )
        return persons_url

    def _breakdown_result_descriptors(self, breakdown_value, filter: Filter, entity: Entity):
        extra_label = self._determine_breakdown_label(
            breakdown_value, filter.breakdown_type, filter.breakdown, breakdown_value
        )
        label = "{} - {}".format(entity.name, extra_label)
        additional_values = {
            "label": label,
        }
        if filter.breakdown_type == "cohort":
            additional_values["breakdown_value"] = "all" if breakdown_value == ALL_USERS_COHORT_ID else breakdown_value
        else:
            additional_values["breakdown_value"] = breakdown_value

        return additional_values

    def _determine_breakdown_label(
        self,
        breakdown_value: int,
        breakdown_type: Optional[str],
        breakdown: Union[str, List[Union[str, int]], None],
        value: Union[str, int],
    ) -> str:
        breakdown = breakdown if breakdown and isinstance(breakdown, list) else []
        if breakdown_type == "cohort":
            return get_breakdown_cohort_name(breakdown_value)
        else:
            return str(value) or "none"

    def _person_join_condition(self) -> Tuple[str, Dict]:
        person_query = PersonQuery(self.filter, self.team_id, self.column_optimizer, entity=self.entity)
        event_join = EVENT_JOIN_PERSON_SQL.format(
            GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(self.team_id)
        )
        if person_query.is_used:
            query, params = person_query.get_query()
            return (
                f"""
            {event_join}
            INNER JOIN ({query}) person
            ON person.id = {self.DISTINCT_ID_TABLE_ALIAS}.person_id
            """,
                params,
            )
        elif self.entity.math == "dau":
            # Only join distinct_ids
            return event_join, {}
        else:
            return "", {}
