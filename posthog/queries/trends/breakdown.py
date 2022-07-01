import urllib.parse
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import pytz
from django.forms import ValidationError

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
from posthog.models.event.sql import EVENT_JOIN_PERSON_SQL
from posthog.models.filters import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property import PropertyGroup
from posthog.models.property.util import get_property_string_expr, parse_prop_grouped_clauses
from posthog.models.team import Team
from posthog.models.utils import PersonPropertiesMode
from posthog.queries.breakdown_props import (
    ALL_USERS_COHORT_ID,
    format_breakdown_cohort_join_query,
    get_breakdown_cohort_name,
    get_breakdown_prop_values,
)
from posthog.queries.column_optimizer.column_optimizer import ColumnOptimizer
from posthog.queries.groups_join_query import GroupsJoinQuery
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query
from posthog.queries.person_query import PersonQuery
from posthog.queries.session_query import SessionQuery
from posthog.queries.trends.sql import (
    BREAKDOWN_ACTIVE_USER_CONDITIONS_SQL,
    BREAKDOWN_ACTIVE_USER_INNER_SQL,
    BREAKDOWN_AGGREGATE_QUERY_SQL,
    BREAKDOWN_COHORT_JOIN_SQL,
    BREAKDOWN_CUMULATIVE_INNER_SQL,
    BREAKDOWN_HISTOGRAM_PROP_JOIN_SQL,
    BREAKDOWN_INNER_SQL,
    BREAKDOWN_PROP_JOIN_SQL,
    BREAKDOWN_QUERY_SQL,
    SESSION_BREAKDOWN_INNER_SQL,
    SESSION_MATH_BREAKDOWN_AGGREGATE_QUERY_SQL,
)
from posthog.queries.trends.util import enumerate_time_range, get_active_user_params, parse_response, process_math
from posthog.queries.util import date_from_clause, get_time_diff, get_trunc_func_ch, parse_timestamps, start_of_week_fix
from posthog.utils import encode_get_request_params


class TrendsBreakdown:
    DISTINCT_ID_TABLE_ALIAS = "pdi"

    def __init__(
        self,
        entity: Entity,
        filter: Filter,
        team: Team,
        column_optimizer: Optional[ColumnOptimizer] = None,
        using_person_on_events: bool = False,
    ):
        self.entity = entity
        self.filter = filter
        self.team = team
        self.team_id = team.pk
        self.params: Dict[str, Any] = {"team_id": team.pk}
        self.column_optimizer = column_optimizer or ColumnOptimizer(self.filter, self.team_id)
        self.using_person_on_events = using_person_on_events

    @cached_property
    def _person_properties_mode(self) -> PersonPropertiesMode:
        return (
            PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN
            if not self.using_person_on_events
            else PersonPropertiesMode.DIRECT_ON_EVENTS
        )

    @cached_property
    def _props_to_filter(self) -> Tuple[str, Dict]:
        props_to_filter = self.filter.property_groups.combine_property_group(
            PropertyOperatorType.AND, self.entity.property_groups
        )

        target_properties: Optional[PropertyGroup] = props_to_filter
        if not self.using_person_on_events:
            target_properties = self.column_optimizer.property_optimizer.parse_property_groups(props_to_filter).outer

        return parse_prop_grouped_clauses(
            team_id=self.team_id,
            property_group=target_properties,
            table_name="e",
            person_properties_mode=self._person_properties_mode,
            person_id_joined_alias=f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id"
            if not self.using_person_on_events
            else "person_id",
        )

    def get_query(self) -> Tuple[str, Dict, Callable]:
        interval_annotation = get_trunc_func_ch(self.filter.interval)
        num_intervals, seconds_in_interval, round_interval = get_time_diff(
            self.filter.interval, self.filter.date_from, self.filter.date_to, self.team_id
        )
        _, parsed_date_to, date_params = parse_timestamps(filter=self.filter, team=self.team)

        prop_filters, prop_filter_params = self._props_to_filter

        aggregate_operation, _, math_params = process_math(
            self.entity,
            self.team,
            event_table_alias="e",
            person_id_alias=f"person_id"
            if self.using_person_on_events
            else f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id",
        )

        action_query = ""
        action_params: Dict = {}
        if self.entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = self.entity.get_action()
            action_query, action_params = format_action_filter(
                team_id=self.team_id,
                action=action,
                table_name="e",
                person_properties_mode=self._person_properties_mode,
                person_id_joined_alias=f"{self.DISTINCT_ID_TABLE_ALIAS if not self.using_person_on_events else 'e'}.person_id",
            )

        self.params = {
            **self.params,
            **math_params,
            **prop_filter_params,
            **action_params,
            "event": self.entity.id,
            "key": self.filter.breakdown,
            **date_params,
            "timezone": self.team.timezone,
        }

        breakdown_filter_params = {
            "parsed_date_from": date_from_clause(interval_annotation, round_interval),
            "parsed_date_to": parsed_date_to,
            "actions_query": "AND {}".format(action_query) if action_query else "",
            "event_filter": "AND event = %(event)s" if not action_query else "",
            "filters": prop_filters,
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
        groups_join_condition, groups_join_params = self._groups_join_condition()
        sessions_join_condition, sessions_join_params = self._sessions_join_condition()
        self.params = {**self.params, **_params, **person_join_params, **groups_join_params, **sessions_join_params}
        breakdown_filter_params = {**breakdown_filter_params, **_breakdown_filter_params}

        if self.filter.display in NON_TIME_SERIES_DISPLAY_TYPES:
            breakdown_filter = breakdown_filter.format(**breakdown_filter_params)

            if self.entity.math_property == "$session_duration":
                # TODO: When we add more person/group properties to math_property,
                # generalise this query to work for everything, not just sessions.
                content_sql = SESSION_MATH_BREAKDOWN_AGGREGATE_QUERY_SQL.format(
                    breakdown_filter=breakdown_filter,
                    person_join=person_join_condition,
                    groups_join=groups_join_condition,
                    sessions_join_condition=sessions_join_condition,
                    aggregate_operation=aggregate_operation,
                    breakdown_value=breakdown_value,
                )
            else:
                content_sql = BREAKDOWN_AGGREGATE_QUERY_SQL.format(
                    breakdown_filter=breakdown_filter,
                    person_join=person_join_condition,
                    groups_join=groups_join_condition,
                    sessions_join_condition=sessions_join_condition,
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
                    sessions_join=sessions_join_condition,
                    person_id_alias=self.DISTINCT_ID_TABLE_ALIAS if not self.using_person_on_events else "e",
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
                    sessions_join=sessions_join_condition,
                    person_id_alias=self.DISTINCT_ID_TABLE_ALIAS if not self.using_person_on_events else "e",
                    aggregate_operation=aggregate_operation,
                    interval_annotation=interval_annotation,
                    breakdown_value=breakdown_value,
                    start_of_week_fix=start_of_week_fix(self.filter),
                    **breakdown_filter_params,
                )
            elif self.entity.math_property == "$session_duration":
                # TODO: When we add more person/group properties to math_property,
                # generalise this query to work for everything, not just sessions.
                inner_sql = SESSION_BREAKDOWN_INNER_SQL.format(
                    breakdown_filter=breakdown_filter,
                    person_join=person_join_condition,
                    groups_join=groups_join_condition,
                    sessions_join=sessions_join_condition,
                    aggregate_operation=aggregate_operation,
                    interval_annotation=interval_annotation,
                    breakdown_value=breakdown_value,
                    start_of_week_fix=start_of_week_fix(self.filter),
                )
            else:
                inner_sql = BREAKDOWN_INNER_SQL.format(
                    breakdown_filter=breakdown_filter,
                    person_join=person_join_condition,
                    groups_join=groups_join_condition,
                    sessions_join=sessions_join_condition,
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
            person_properties_mode=self._person_properties_mode,
        )

        # :TRICKY: We only support string breakdown for event/person properties
        assert isinstance(self.filter.breakdown, str)

        breakdown_value = self._get_breakdown_value(self.filter.breakdown)

        if self.filter.using_histogram:
            breakdown_value, values_arr = self._get_histogram_breakdown_values(breakdown_value, values_arr)

        return (
            {"values": values_arr},
            BREAKDOWN_PROP_JOIN_SQL if not self.filter.using_histogram else BREAKDOWN_HISTOGRAM_PROP_JOIN_SQL,
            {"breakdown_value_expr": breakdown_value},
            breakdown_value,
        )

    def _get_breakdown_value(self, breakdown: str):

        if self.filter.breakdown_type == "session":
            if breakdown == "$session_duration":
                return f"{SessionQuery.SESSION_TABLE_ALIAS}.session_duration"
            else:
                raise ValidationError(f'Invalid breakdown "{breakdown}" for breakdown type "session"')

        if self.using_person_on_events:
            if self.filter.breakdown_type == "person":
                breakdown_value, _ = get_property_string_expr("events", breakdown, "%(key)s", "person_properties")
            elif self.filter.breakdown_type == "group":
                properties_field = f"group{self.filter.breakdown_group_type_index}_properties"
                breakdown_value, _ = get_property_string_expr("events", breakdown, "%(key)s", properties_field)
            else:
                breakdown_value, _ = get_property_string_expr("events", breakdown, "%(key)s", "properties")

            return breakdown_value

        else:
            if self.filter.breakdown_type == "person":
                breakdown_value, _ = get_property_string_expr("person", breakdown, "%(key)s", "person_props")
            elif self.filter.breakdown_type == "group":
                properties_field = f"group_properties_{self.filter.breakdown_group_type_index}"
                breakdown_value, _ = get_property_string_expr("groups", breakdown, "%(key)s", properties_field)
            else:
                breakdown_value, _ = get_property_string_expr("events", breakdown, "%(key)s", "properties")

            return breakdown_value

    def _get_histogram_breakdown_values(self, raw_breakdown_value: str, buckets: List[int]):

        multi_if_conditionals = []
        values_arr = []

        for i in range(len(buckets) - 1):
            last_bucket = i == len(buckets) - 2

            multi_if_conditionals.append(
                f"{raw_breakdown_value} >= {buckets[i]} AND {raw_breakdown_value} {'<=' if last_bucket else '<'} {buckets[i+1]}"
            )
            multi_if_conditionals.append(f"'{buckets[i]},{buckets[i+1]}'")
            values_arr.append(f"{buckets[i]},{buckets[i+1]}")

        # else condition
        multi_if_conditionals.append(f"','")

        return f"multiIf({','.join(multi_if_conditionals)})", values_arr

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
                            filter, entity, self.team_id, stats[0], result_descriptors["breakdown_value"]
                        )
                    }
                )
                parsed_results.append(parsed_result)
                parsed_result.update({"filter": filter.to_dict()})
            return sorted(parsed_results, key=lambda x: 0 if x.get("breakdown_value") != "all" else 1)

        return _parse

    def _get_persons_url(
        self, filter: Filter, entity: Entity, team_id: int, dates: List[datetime], breakdown_value: Union[str, int]
    ) -> List[Dict[str, Any]]:
        persons_url = []
        for date in dates:
            date_in_utc = datetime(
                date.year,
                date.month,
                date.day,
                getattr(date, "hour", 0),
                getattr(date, "minute", 0),
                getattr(date, "second", 0),
                tzinfo=getattr(date, "tzinfo", pytz.UTC),
            ).astimezone(pytz.UTC)
            filter_params = filter.to_params()
            extra_params = {
                "entity_id": entity.id,
                "entity_type": entity.type,
                "entity_math": entity.math,
                "date_from": filter.date_from if filter.display == TRENDS_CUMULATIVE else date_in_utc,
                "date_to": date_in_utc,
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
        if self.using_person_on_events:
            return "", {}

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
        elif (
            self.entity.math in ["dau", WEEKLY_ACTIVE, MONTHLY_ACTIVE]
            or self.column_optimizer.is_using_cohort_propertes
        ):
            # Only join distinct_ids
            return event_join, {}
        else:
            return "", {}

    def _groups_join_condition(self) -> Tuple[str, Dict]:
        return GroupsJoinQuery(
            self.filter, self.team_id, self.column_optimizer, using_person_on_events=self.using_person_on_events
        ).get_join_query()

    def _sessions_join_condition(self) -> Tuple[str, Dict]:
        if self.filter.breakdown_type == "session" or self.entity.math_property == "$session_duration":
            session_query, session_params = SessionQuery(filter=self.filter, team=self.team).get_query()
            return (
                f"""
                    INNER JOIN ({session_query}) {SessionQuery.SESSION_TABLE_ALIAS}
                    ON {SessionQuery.SESSION_TABLE_ALIAS}.$session_id = e.$session_id
                """,
                session_params,
            )
        return "", {}
