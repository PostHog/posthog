import json
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
    UNIQUE_USERS,
    WEEKLY_ACTIVE,
    PropertyOperatorType,
)
from posthog.models.action.util import format_action_filter
from posthog.models.entity import Entity
from posthog.models.event.sql import EVENT_JOIN_PERSON_SQL
from posthog.models.filters import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property import PropertyGroup
from posthog.models.property.util import get_property_string_expr, normalize_url_breakdown, parse_prop_grouped_clauses
from posthog.models.team import Team
from posthog.models.team.team import groups_on_events_querying_enabled
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
from posthog.queries.query_date_range import TIME_IN_SECONDS, QueryDateRange
from posthog.queries.session_query import SessionQuery
from posthog.queries.trends.sql import (
    BREAKDOWN_ACTIVE_USER_AGGREGATE_SQL,
    BREAKDOWN_ACTIVE_USER_CONDITIONS_SQL,
    BREAKDOWN_ACTIVE_USER_INNER_SQL,
    BREAKDOWN_AGGREGATE_QUERY_SQL,
    BREAKDOWN_COHORT_JOIN_SQL,
    BREAKDOWN_CUMULATIVE_INNER_SQL,
    BREAKDOWN_HISTOGRAM_PROP_JOIN_SQL,
    BREAKDOWN_INNER_SQL,
    BREAKDOWN_PROP_JOIN_SQL,
    BREAKDOWN_QUERY_SQL,
    SESSION_DURATION_BREAKDOWN_AGGREGATE_SQL,
    SESSION_DURATION_BREAKDOWN_INNER_SQL,
    VOLUME_PER_ACTOR_BREAKDOWN_AGGREGATE_SQL,
    VOLUME_PER_ACTOR_BREAKDOWN_INNER_SQL,
)
from posthog.queries.trends.util import (
    COUNT_PER_ACTOR_MATH_FUNCTIONS,
    PROPERTY_MATH_FUNCTIONS,
    ensure_value_is_json_serializable,
    enumerate_time_range,
    get_active_user_params,
    parse_response,
    process_math,
)
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
    def actor_aggregator(self) -> str:
        if self.team.aggregate_users_by_distinct_id:
            return "e.distinct_id"
        return f"{'e' if self._person_properties_mode == PersonPropertiesMode.DIRECT_ON_EVENTS else 'pdi'}.person_id"

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
            hogql_context=self.filter.hogql_context,
        )

    def get_query(self) -> Tuple[str, Dict, Callable]:
        date_params = {}

        query_date_range = QueryDateRange(filter=self.filter, team=self.team)
        parsed_date_from, date_from_params = query_date_range.date_from
        parsed_date_to, date_to_params = query_date_range.date_to
        num_intervals = query_date_range.num_intervals
        seconds_in_interval = TIME_IN_SECONDS[self.filter.interval]
        interval_annotation = query_date_range.interval_annotation

        date_params.update(date_from_params)
        date_params.update(date_to_params)

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
                hogql_context=self.filter.hogql_context,
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
            "parsed_date_from": parsed_date_from,
            "parsed_date_to": parsed_date_to,
            "actions_query": "AND {}".format(action_query) if action_query else "",
            "event_filter": "AND event = %(event)s" if not action_query else "",
            "filters": prop_filters,
            "null_person_filter": f"AND notEmpty(e.person_id)" if self.using_person_on_events else "",
        }

        _params, _breakdown_filter_params = {}, {}

        if self.filter.breakdown_type == "cohort":
            _params, breakdown_filter, _breakdown_filter_params, breakdown_value = self._breakdown_cohort_params()
        else:
            aggregate_operation_for_breakdown_init = (
                "count(*)"
                if self.entity.math == "dau" or self.entity.math in COUNT_PER_ACTOR_MATH_FUNCTIONS
                else aggregate_operation
            )
            _params, breakdown_filter, _breakdown_filter_params, breakdown_value = self._breakdown_prop_params(
                aggregate_operation_for_breakdown_init, math_params
            )

        if len(_params["values"]) == 0:
            # If there are no breakdown values, we are sure that there's no relevant events, so instead of adjusting
            # a "real" SELECT for this, we only include the below dummy SELECT.
            # It's a drop-in replacement for a "real" one, simply always returning 0 rows.
            # See https://github.com/PostHog/posthog/pull/5674 for context.
            return ("SELECT [now()] AS date, [0] AS data, '' AS breakdown_value LIMIT 0", {}, lambda _: [])

        person_join_condition, person_join_params = self._person_join_condition()
        groups_join_condition, groups_join_params = self._groups_join_condition()
        sessions_join_condition, sessions_join_params = self._sessions_join_condition()
        self.params = {**self.params, **_params, **person_join_params, **groups_join_params, **sessions_join_params}
        breakdown_filter_params = {**breakdown_filter_params, **_breakdown_filter_params}

        if self.filter.display in NON_TIME_SERIES_DISPLAY_TYPES:
            breakdown_filter = breakdown_filter.format(**breakdown_filter_params)

            if self.entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
                active_user_format_params, active_user_query_params = get_active_user_params(
                    self.filter, self.entity, self.team_id
                )
                self.params.update(active_user_query_params)
                conditions = BREAKDOWN_ACTIVE_USER_CONDITIONS_SQL.format(
                    **breakdown_filter_params, **active_user_format_params
                )
                content_sql = BREAKDOWN_ACTIVE_USER_AGGREGATE_SQL.format(
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
                    **active_user_format_params,
                    **breakdown_filter_params,
                )
            elif self.entity.math in PROPERTY_MATH_FUNCTIONS and self.entity.math_property == "$session_duration":
                # TODO: When we add more person/group properties to math_property,
                # generalise this query to work for everything, not just sessions.
                content_sql = SESSION_DURATION_BREAKDOWN_AGGREGATE_SQL.format(
                    breakdown_filter=breakdown_filter,
                    person_join=person_join_condition,
                    groups_join=groups_join_condition,
                    sessions_join_condition=sessions_join_condition,
                    aggregate_operation=aggregate_operation,
                    breakdown_value=breakdown_value,
                    event_sessions_table_alias=SessionQuery.SESSION_TABLE_ALIAS,
                )
            elif self.entity.math in COUNT_PER_ACTOR_MATH_FUNCTIONS:
                content_sql = VOLUME_PER_ACTOR_BREAKDOWN_AGGREGATE_SQL.format(
                    breakdown_filter=breakdown_filter,
                    person_join=person_join_condition,
                    groups_join=groups_join_condition,
                    sessions_join_condition=sessions_join_condition,
                    aggregate_operation=aggregate_operation,
                    aggregator=self.actor_aggregator,
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
                active_user_format_params, active_user_query_params = get_active_user_params(
                    self.filter, self.entity, self.team_id
                )
                self.params.update(active_user_query_params)
                conditions = BREAKDOWN_ACTIVE_USER_CONDITIONS_SQL.format(
                    **breakdown_filter_params, **active_user_format_params
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
                    **active_user_format_params,
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
                    **breakdown_filter_params,
                )
            elif self.entity.math in PROPERTY_MATH_FUNCTIONS and self.entity.math_property == "$session_duration":
                # TODO: When we add more person/group properties to math_property,
                # generalise this query to work for everything, not just sessions.
                inner_sql = SESSION_DURATION_BREAKDOWN_INNER_SQL.format(
                    breakdown_filter=breakdown_filter,
                    person_join=person_join_condition,
                    groups_join=groups_join_condition,
                    sessions_join=sessions_join_condition,
                    aggregate_operation=aggregate_operation,
                    interval_annotation=interval_annotation,
                    breakdown_value=breakdown_value,
                    event_sessions_table_alias=SessionQuery.SESSION_TABLE_ALIAS,
                    **breakdown_filter_params,
                )
            elif self.entity.math in COUNT_PER_ACTOR_MATH_FUNCTIONS:
                inner_sql = VOLUME_PER_ACTOR_BREAKDOWN_INNER_SQL.format(
                    breakdown_filter=breakdown_filter,
                    person_join=person_join_condition,
                    groups_join=groups_join_condition,
                    sessions_join=sessions_join_condition,
                    aggregate_operation=aggregate_operation,
                    interval_annotation=interval_annotation,
                    aggregator=self.actor_aggregator,
                    breakdown_value=breakdown_value,
                    **breakdown_filter_params,
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
                    **breakdown_filter_params,
                )

            breakdown_query = BREAKDOWN_QUERY_SQL.format(
                interval=interval_annotation, num_intervals=num_intervals, inner_sql=inner_sql
            )
            self.params.update({"seconds_in_interval": seconds_in_interval, "num_intervals": num_intervals})
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
        numeric_property_filter = ""
        if self.filter.using_histogram:
            numeric_property_filter = f"AND {breakdown_value} is not null"
            breakdown_value, values_arr = self._get_histogram_breakdown_values(breakdown_value, values_arr)

        return (
            {"values": values_arr},
            BREAKDOWN_PROP_JOIN_SQL if not self.filter.using_histogram else BREAKDOWN_HISTOGRAM_PROP_JOIN_SQL,
            {"breakdown_value_expr": breakdown_value, "numeric_property_filter": numeric_property_filter},
            breakdown_value,
        )

    def _get_breakdown_value(self, breakdown: str) -> str:
        if self.filter.breakdown_type == "hogql":
            from posthog.hogql.hogql import translate_hogql

            breakdown_value = translate_hogql(breakdown, self.filter.hogql_context)

        elif self.filter.breakdown_type == "session":
            if breakdown == "$session_duration":
                # Return the session duration expression right away because it's already an number,
                # so it doesn't need casting for the histogram case (like the other properties)
                breakdown_value = f"{SessionQuery.SESSION_TABLE_ALIAS}.session_duration"
            else:
                raise ValidationError(f'Invalid breakdown "{breakdown}" for breakdown type "session"')

        elif (
            self.using_person_on_events
            and self.filter.breakdown_type == "group"
            and groups_on_events_querying_enabled()
        ):
            properties_field = f"group{self.filter.breakdown_group_type_index}_properties"
            breakdown_value, _ = get_property_string_expr(
                "events", breakdown, "%(key)s", properties_field, materialised_table_column=properties_field
            )
        elif self.using_person_on_events and self.filter.breakdown_type != "group":
            if self.filter.breakdown_type == "person":
                breakdown_value, _ = get_property_string_expr(
                    "events", breakdown, "%(key)s", "person_properties", materialised_table_column="person_properties"
                )
            else:
                breakdown_value, _ = get_property_string_expr("events", breakdown, "%(key)s", "properties")
        else:
            if self.filter.breakdown_type == "person":
                breakdown_value, _ = get_property_string_expr("person", breakdown, "%(key)s", "person_props")
            elif self.filter.breakdown_type == "group":
                properties_field = f"group_properties_{self.filter.breakdown_group_type_index}"
                breakdown_value, _ = get_property_string_expr(
                    "groups", breakdown, "%(key)s", properties_field, materialised_table_column="group_properties"
                )
            else:
                breakdown_value, _ = get_property_string_expr("events", breakdown, "%(key)s", "properties")

        if self.filter.using_histogram:
            breakdown_value = f"toFloat64OrNull(toString({breakdown_value}))"

        breakdown_value = normalize_url_breakdown(breakdown_value, self.filter.breakdown_normalize_url)

        return breakdown_value

    def _get_histogram_breakdown_values(self, raw_breakdown_value: str, buckets: List[int]):

        multi_if_conditionals = []
        values_arr = []

        if len(buckets) == 1:
            # Only one value, so treat this as a single bucket
            # starting at this value, ending at the same value.
            buckets = [buckets[0], buckets[0]]

        for i in range(len(buckets) - 1):
            last_bucket = i == len(buckets) - 2

            # Since we always `floor(x, 2)` the value, we add 0.01 to the last bucket
            # to ensure it's always slightly greater than the maximum value
            lower_bound = buckets[i]
            upper_bound = buckets[i + 1] + 0.01 if last_bucket else buckets[i + 1]
            multi_if_conditionals.append(
                f"{raw_breakdown_value} >= {lower_bound} AND {raw_breakdown_value} < {upper_bound}"
            )
            bucket_value = f"[{lower_bound},{upper_bound}]"
            multi_if_conditionals.append(f"'{bucket_value}'")
            values_arr.append(bucket_value)

        # else condition
        multi_if_conditionals.append(f"""'["",""]'""")

        return f"multiIf({','.join(multi_if_conditionals)})", values_arr

    def breakdown_sort_function(self, value):
        if self.filter.using_histogram:
            return json.loads(value.get("breakdown_value"))[0]
        if value.get("breakdown_value") == "all":
            return (-1, "")
        if self.filter.breakdown_type == "session":
            # if session duration breakdown, we want ordering based on the time buckets, not the value
            return (-1, "")

        count_or_aggregated_value = value.get("count", value.get("aggregated_value") or 0)
        return count_or_aggregated_value * -1, value.get("label")  # reverse it

    def _parse_single_aggregate_result(
        self, filter: Filter, entity: Entity, additional_values: Dict[str, Any]
    ) -> Callable:
        def _parse(result: List) -> List:
            parsed_results = []
            for stats in result:
                aggregated_value = ensure_value_is_json_serializable(stats[0])
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
                    "aggregated_value": aggregated_value,
                    "filter": filter_params,
                    "persons": {
                        "filter": extra_params,
                        "url": f"api/projects/{self.team_id}/persons/trends/?{urllib.parse.urlencode(parsed_params)}",
                    },
                    **result_descriptors,
                    **additional_values,
                }
                parsed_results.append(parsed_result)
            try:
                return sorted(parsed_results, key=lambda x: self.breakdown_sort_function(x))
            except TypeError:
                return sorted(parsed_results, key=lambda x: str(self.breakdown_sort_function(x)))

        return _parse

    def _parse_trend_result(self, filter: Filter, entity: Entity) -> Callable:
        def _parse(result: List) -> List:
            parsed_results = []
            for stats in result:
                result_descriptors = self._breakdown_result_descriptors(stats[2], filter, entity)
                parsed_result = parse_response(stats, filter, additional_values=result_descriptors, entity=entity)
                parsed_result.update(
                    {
                        "persons_urls": self._get_persons_url(
                            filter, entity, self.team_id, stats[0], result_descriptors["breakdown_value"]
                        )
                    }
                )
                parsed_results.append(parsed_result)
                parsed_result.update({"filter": filter.to_dict()})

            try:
                return sorted(parsed_results, key=lambda x: self.breakdown_sort_function(x))
            except TypeError:
                return sorted(parsed_results, key=lambda x: str(self.breakdown_sort_function(x)))

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
                    "url": f"api/projects/{team_id}/persons/trends/?{urllib.parse.urlencode(parsed_params)}",
                }
            )
        return persons_url

    def _breakdown_result_descriptors(self, breakdown_value, filter: Filter, entity: Entity):
        extra_label = self._determine_breakdown_label(
            breakdown_value, filter.breakdown_type, filter.breakdown, breakdown_value
        )
        label = "{} - {}".format(entity.name, extra_label)
        additional_values = {"label": label}
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
            self.entity.math in [UNIQUE_USERS, WEEKLY_ACTIVE, MONTHLY_ACTIVE]
            and not self.team.aggregate_users_by_distinct_id
        ) or self.column_optimizer.is_using_cohort_propertes:
            # Only join distinct_ids
            return event_join, {}
        else:
            return "", {}

    def _groups_join_condition(self) -> Tuple[str, Dict]:
        return GroupsJoinQuery(
            self.filter, self.team_id, self.column_optimizer, using_person_on_events=self.using_person_on_events
        ).get_join_query()

    def _sessions_join_condition(self) -> Tuple[str, Dict]:
        session_query = SessionQuery(filter=self.filter, team=self.team)
        if session_query.is_used:
            query, session_params = session_query.get_query()
            return (
                f"""
                    INNER JOIN ({query}) {SessionQuery.SESSION_TABLE_ALIAS}
                    ON {SessionQuery.SESSION_TABLE_ALIAS}.$session_id = e.$session_id
                """,
                session_params,
            )
        return "", {}
