import re
import json
import urllib.parse
from collections.abc import Callable
from datetime import datetime
from typing import Any, Optional, Union
from zoneinfo import ZoneInfo

from django.forms import ValidationError

from posthog.schema import PersonsOnEventsMode

from posthog.constants import (
    MONTHLY_ACTIVE,
    NON_TIME_SERIES_DISPLAY_TYPES,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
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
from posthog.queries.breakdown_props import (
    ALL_USERS_COHORT_ID,
    format_breakdown_cohort_join_query,
    get_breakdown_cohort_name,
    get_breakdown_prop_values,
)
from posthog.queries.column_optimizer.column_optimizer import ColumnOptimizer
from posthog.queries.event_query import EventQuery
from posthog.queries.groups_join_query import GroupsJoinQuery
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query
from posthog.queries.person_on_events_v2_sql import PERSON_DISTINCT_ID_OVERRIDES_JOIN_SQL
from posthog.queries.person_query import PersonQuery
from posthog.queries.query_date_range import TIME_IN_SECONDS, QueryDateRange
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
    BREAKDOWN_PROP_JOIN_WITH_OTHER_SQL,
    BREAKDOWN_QUERY_SQL,
    SESSION_DURATION_BREAKDOWN_AGGREGATE_SQL,
    SESSION_DURATION_BREAKDOWN_INNER_SQL,
    VOLUME_PER_ACTOR_BREAKDOWN_AGGREGATE_SQL,
    VOLUME_PER_ACTOR_BREAKDOWN_INNER_SQL,
)
from posthog.queries.trends.util import (
    COUNT_PER_ACTOR_MATH_FUNCTIONS,
    PROPERTY_MATH_FUNCTIONS,
    correct_result_for_sampling,
    enumerate_time_range,
    get_active_user_params,
    offset_time_series_date_by_interval,
    parse_response,
    process_math,
)
from posthog.queries.util import (
    alias_poe_mode_for_legacy,
    get_interval_func_ch,
    get_person_properties_mode,
    get_start_of_interval_sql,
)
from posthog.session_recordings.queries.session_query import SessionQuery
from posthog.utils import encode_get_request_params, generate_short_id

BREAKDOWN_OTHER_DISPLAY = "Other (i.e. all remaining values)"
BREAKDOWN_NULL_DISPLAY = "None (i.e. no value)"


BREAKDOWN_OTHER_STRING_LABEL = "$$_posthog_breakdown_other_$$"
BREAKDOWN_OTHER_NUMERIC_LABEL = 9007199254740991  # pow(2, 53) - 1, for JS compatibility
BREAKDOWN_NULL_STRING_LABEL = "$$_posthog_breakdown_null_$$"
BREAKDOWN_NULL_NUMERIC_LABEL = 9007199254740990  # pow(2, 53) - 2, for JS compatibility


class TrendsBreakdown:
    DISTINCT_ID_TABLE_ALIAS = EventQuery.DISTINCT_ID_TABLE_ALIAS
    EVENT_TABLE_ALIAS = EventQuery.EVENT_TABLE_ALIAS
    PERSON_ID_OVERRIDES_TABLE_ALIAS = EventQuery.PERSON_ID_OVERRIDES_TABLE_ALIAS

    def __init__(
        self,
        entity: Entity,
        filter: Filter,
        team: Team,
        column_optimizer: Optional[ColumnOptimizer] = None,
        person_on_events_mode: PersonsOnEventsMode = PersonsOnEventsMode.DISABLED,
        add_person_urls: bool = False,
    ):
        self.entity = entity
        self.filter = filter
        self.team = team
        self.team_id = team.pk
        self.params: dict[str, Any] = {"team_id": team.pk}
        self.column_optimizer = column_optimizer or ColumnOptimizer(self.filter, self.team_id)
        self.add_person_urls = add_person_urls
        self.person_on_events_mode = alias_poe_mode_for_legacy(person_on_events_mode)
        if person_on_events_mode == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS:
            self._person_id_alias = f"if(notEmpty({self.PERSON_ID_OVERRIDES_TABLE_ALIAS}.distinct_id), {self.PERSON_ID_OVERRIDES_TABLE_ALIAS}.person_id, {self.EVENT_TABLE_ALIAS}.person_id)"
        elif person_on_events_mode == PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS:
            self._person_id_alias = f"{self.EVENT_TABLE_ALIAS}.person_id"
        else:
            self._person_id_alias = f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id"

    @cached_property
    def actor_aggregator(self) -> str:
        if self.team.aggregate_users_by_distinct_id:
            return "e.distinct_id"
        return self._person_id_alias

    @cached_property
    def _props_to_filter(self) -> tuple[str, dict]:
        props_to_filter = self.filter.property_groups.combine_property_group(
            PropertyOperatorType.AND, self.entity.property_groups
        )

        target_properties: Optional[PropertyGroup] = props_to_filter
        if self.person_on_events_mode == PersonsOnEventsMode.DISABLED:
            target_properties = self.column_optimizer.property_optimizer.parse_property_groups(props_to_filter).outer

        return parse_prop_grouped_clauses(
            team_id=self.team_id,
            property_group=target_properties,
            table_name=self.EVENT_TABLE_ALIAS,
            person_properties_mode=get_person_properties_mode(self.team),
            person_id_joined_alias=self._person_id_alias,
            hogql_context=self.filter.hogql_context,
        )

    def get_query(self) -> tuple[str, dict, Callable]:
        date_params = {}

        query_date_range = QueryDateRange(filter=self.filter, team=self.team)
        parsed_date_from, date_from_params = query_date_range.date_from
        parsed_date_to, date_to_params = query_date_range.date_to
        num_intervals = query_date_range.num_intervals
        seconds_in_interval = TIME_IN_SECONDS[self.filter.interval]

        date_params.update(date_from_params)
        date_params.update(date_to_params)

        prop_filters, prop_filter_params = self._props_to_filter

        aggregate_operation, _, math_params = process_math(
            self.entity,
            self.team,
            filter=self.filter,
            event_table_alias=self.EVENT_TABLE_ALIAS,
            person_id_alias=(
                f"person_id"
                if self.person_on_events_mode == PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS
                else self._person_id_alias
            ),
        )

        action_query = ""
        action_params: dict = {}
        if self.entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = self.entity.get_action()
            action_query, action_params = format_action_filter(
                team_id=self.team_id,
                action=action,
                table_name=self.EVENT_TABLE_ALIAS,
                person_properties_mode=get_person_properties_mode(self.team),
                person_id_joined_alias=self._person_id_alias,
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
            "event_filter": (
                "AND event = %(event)s"
                if self.entity.type == TREND_FILTER_TYPE_EVENTS and self.entity.id is not None
                else ""
            ),
            "filters": prop_filters,
            "null_person_filter": (
                f"AND notEmpty(e.person_id)" if self.person_on_events_mode != PersonsOnEventsMode.DISABLED else ""
            ),
        }

        _params, _breakdown_filter_params = {}, {}

        if self.filter.breakdown_type == "cohort":
            (
                _params,
                breakdown_filter,
                _breakdown_filter_params,
                breakdown_value,
            ) = self._breakdown_cohort_params()
        else:
            aggregate_operation_for_breakdown_init = (
                "count(*)"
                if self.entity.math == "dau" or self.entity.math in COUNT_PER_ACTOR_MATH_FUNCTIONS
                else aggregate_operation
            )
            (
                _params,
                breakdown_filter,
                _breakdown_filter_params,
                breakdown_value,
            ) = self._breakdown_prop_params(aggregate_operation_for_breakdown_init, math_params)

        if len(_params["values"]) == 0:
            # If there are no breakdown values, we are sure that there's no relevant events, so instead of adjusting
            # a "real" SELECT for this, we only include the below dummy SELECT.
            # It's a drop-in replacement for a "real" one, simply always returning 0 rows.
            # See https://github.com/PostHog/posthog/pull/5674 for context.
            return (
                "SELECT [now()] AS date, [0] AS total, '' AS breakdown_value LIMIT 0",
                {},
                lambda _: [],
            )

        person_join_condition, person_join_params = self._person_join_condition()
        groups_join_condition, groups_join_params = self._groups_join_condition()
        sessions_join_condition, sessions_join_params = self._sessions_join_condition()

        sample_clause = "SAMPLE %(sampling_factor)s" if self.filter.sampling_factor else ""
        sampling_params = {"sampling_factor": self.filter.sampling_factor}

        self.params = {
            **self.params,
            **_params,
            **person_join_params,
            **groups_join_params,
            **sessions_join_params,
            **sampling_params,
        }
        breakdown_filter_params = {
            **breakdown_filter_params,
            **_breakdown_filter_params,
        }

        if self.filter.display in NON_TIME_SERIES_DISPLAY_TYPES:
            breakdown_filter = breakdown_filter.format(**breakdown_filter_params)

            if self.entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
                interval_func = get_interval_func_ch(self.filter.interval)
                (
                    active_user_format_params,
                    active_user_query_params,
                ) = get_active_user_params(self.filter, self.entity, self.team_id)
                self.params.update(active_user_query_params)
                conditions = BREAKDOWN_ACTIVE_USER_CONDITIONS_SQL.format(
                    **breakdown_filter_params, **active_user_format_params
                )
                content_sql = BREAKDOWN_ACTIVE_USER_AGGREGATE_SQL.format(
                    breakdown_filter=breakdown_filter,
                    person_join=person_join_condition,
                    groups_join=groups_join_condition,
                    sessions_join=sessions_join_condition,
                    aggregate_operation=aggregate_operation,
                    timestamp_truncated=get_start_of_interval_sql(self.filter.interval, team=self.team),
                    date_to_truncated=get_start_of_interval_sql(
                        self.filter.interval, team=self.team, source="%(date_to)s"
                    ),
                    interval_func=interval_func,
                    breakdown_value=breakdown_value,
                    conditions=conditions,
                    GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(self.team_id),
                    sample_clause=sample_clause,
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
                    sample_clause=sample_clause,
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
                    sample_clause=sample_clause,
                )
            else:
                content_sql = BREAKDOWN_AGGREGATE_QUERY_SQL.format(
                    breakdown_filter=breakdown_filter,
                    person_join=person_join_condition,
                    groups_join=groups_join_condition,
                    sessions_join_condition=sessions_join_condition,
                    aggregate_operation=aggregate_operation,
                    breakdown_value=breakdown_value,
                    sample_clause=sample_clause,
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
                (
                    active_user_format_params,
                    active_user_query_params,
                ) = get_active_user_params(self.filter, self.entity, self.team_id)
                self.params.update(active_user_query_params)
                conditions = BREAKDOWN_ACTIVE_USER_CONDITIONS_SQL.format(
                    **breakdown_filter_params, **active_user_format_params
                )
                inner_sql = BREAKDOWN_ACTIVE_USER_INNER_SQL.format(
                    breakdown_filter=breakdown_filter,
                    person_join=person_join_condition,
                    groups_join=groups_join_condition,
                    sessions_join=sessions_join_condition,
                    person_id_alias=self._person_id_alias,
                    aggregate_operation=aggregate_operation,
                    timestamp_truncated=get_start_of_interval_sql(self.filter.interval, team=self.team),
                    breakdown_value=breakdown_value,
                    conditions=conditions,
                    GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(self.team_id),
                    sample_clause=sample_clause,
                    **active_user_format_params,
                    **breakdown_filter_params,
                )
            elif self.filter.display == TRENDS_CUMULATIVE and self.entity.math == "dau":
                # TRICKY: This is a subquery, so the person_id_alias expression is not available in the outer query.
                # Hence, we overwrite the aggregation_operation with the apprioriate one for the outer query.
                cummulative_aggregate_operation = f"count(DISTINCT person_id)"

                inner_sql = BREAKDOWN_CUMULATIVE_INNER_SQL.format(
                    breakdown_filter=breakdown_filter,
                    person_join=person_join_condition,
                    groups_join=groups_join_condition,
                    sessions_join=sessions_join_condition,
                    person_id_alias=self._person_id_alias,
                    aggregate_operation=cummulative_aggregate_operation,
                    timestamp_truncated=get_start_of_interval_sql(self.filter.interval, team=self.team),
                    breakdown_value=breakdown_value,
                    sample_clause=sample_clause,
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
                    timestamp_truncated=get_start_of_interval_sql(self.filter.interval, team=self.team),
                    breakdown_value=breakdown_value,
                    event_sessions_table_alias=SessionQuery.SESSION_TABLE_ALIAS,
                    sample_clause=sample_clause,
                    **breakdown_filter_params,
                )
            elif self.entity.math in COUNT_PER_ACTOR_MATH_FUNCTIONS:
                inner_sql = VOLUME_PER_ACTOR_BREAKDOWN_INNER_SQL.format(
                    breakdown_filter=breakdown_filter,
                    person_join=person_join_condition,
                    groups_join=groups_join_condition,
                    sessions_join=sessions_join_condition,
                    aggregate_operation=aggregate_operation,
                    timestamp_truncated=get_start_of_interval_sql(self.filter.interval, team=self.team),
                    aggregator=self.actor_aggregator,
                    breakdown_value=breakdown_value,
                    sample_clause=sample_clause,
                    **breakdown_filter_params,
                )
            else:
                inner_sql = BREAKDOWN_INNER_SQL.format(
                    breakdown_filter=breakdown_filter,
                    person_join=person_join_condition,
                    groups_join=groups_join_condition,
                    sessions_join=sessions_join_condition,
                    aggregate_operation=aggregate_operation,
                    timestamp_truncated=get_start_of_interval_sql(self.filter.interval, team=self.team),
                    breakdown_value=breakdown_value,
                    sample_clause=sample_clause,
                    **breakdown_filter_params,
                )

            breakdown_query = BREAKDOWN_QUERY_SQL.format(
                num_intervals=num_intervals,
                inner_sql=inner_sql,
                date_from_truncated=get_start_of_interval_sql(
                    self.filter.interval, team=self.team, source="%(date_from)s"
                ),
                date_to_truncated=get_start_of_interval_sql(self.filter.interval, team=self.team, source="%(date_to)s"),
                interval_func=get_interval_func_ch(self.filter.interval),
            )
            self.params.update(
                {
                    "seconds_in_interval": seconds_in_interval,
                    "num_intervals": num_intervals,
                }
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

    def _breakdown_prop_params(self, aggregate_operation: str, math_params: dict):
        values_arr, has_more_values = get_breakdown_prop_values(
            self.filter,
            self.entity,
            aggregate_operation,
            self.team,
            extra_params=math_params,
            column_optimizer=self.column_optimizer,
            person_properties_mode=get_person_properties_mode(self.team),
        )

        # :TRICKY: We only support string breakdown for event/person properties
        assert isinstance(self.filter.breakdown, str)

        breakdown_value = self._get_breakdown_value(self.filter.breakdown)
        breakdown_other_value: str | int = BREAKDOWN_OTHER_STRING_LABEL
        breakdown_null_value: str | int = BREAKDOWN_NULL_STRING_LABEL
        numeric_property_filter = ""
        if self.filter.using_histogram:
            numeric_property_filter = f"AND {breakdown_value} is not null"
            breakdown_value, values_arr = self._get_histogram_breakdown_values(breakdown_value, values_arr)

        elif self.filter.breakdown_type == "session" and self.filter.breakdown == "$session_duration":
            # Not adding "Other" for the custom session duration filter.
            pass
        else:
            all_values_are_numeric_or_none = all(
                isinstance(value, int) or isinstance(value, float) or value is None for value in values_arr
            )
            all_values_are_string_or_none = all(isinstance(value, str) or value is None for value in values_arr)

            if all_values_are_numeric_or_none:
                breakdown_other_value = BREAKDOWN_OTHER_NUMERIC_LABEL
                breakdown_null_value = BREAKDOWN_NULL_NUMERIC_LABEL
                values_arr = [BREAKDOWN_NULL_NUMERIC_LABEL if value is None else value for value in values_arr]
            else:
                if not all_values_are_string_or_none:
                    breakdown_value = f"toString({breakdown_value})"
                breakdown_value = f"nullIf({breakdown_value}, '')"
                values_arr = [BREAKDOWN_NULL_STRING_LABEL if value in (None, "") else value for value in values_arr]
            breakdown_value = f"transform(ifNull({breakdown_value}, %(breakdown_null_value)s), (%(values)s), (%(values)s), %(breakdown_other_value)s)"

        if self.filter.using_histogram:
            sql_query = BREAKDOWN_HISTOGRAM_PROP_JOIN_SQL
        elif self.filter.breakdown_hide_other_aggregation:
            sql_query = BREAKDOWN_PROP_JOIN_SQL
        else:
            sql_query = BREAKDOWN_PROP_JOIN_WITH_OTHER_SQL

        return (
            {
                "values": (
                    [*values_arr, breakdown_other_value]
                    if has_more_values and not self.filter.breakdown_hide_other_aggregation
                    else values_arr
                ),
                "breakdown_other_value": breakdown_other_value,
                "breakdown_null_value": breakdown_null_value,
            },
            sql_query,
            {
                "breakdown_value_expr": breakdown_value,
                "numeric_property_filter": numeric_property_filter,
            },
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
        elif self.person_on_events_mode != PersonsOnEventsMode.DISABLED and self.filter.breakdown_type != "group":
            if self.filter.breakdown_type == "person":
                breakdown_value, _ = get_property_string_expr(
                    "events",
                    breakdown,
                    "%(key)s",
                    "person_properties",
                    materialised_table_column="person_properties",
                )
            else:
                breakdown_value, _ = get_property_string_expr("events", breakdown, "%(key)s", "properties")
        else:
            if self.filter.breakdown_type == "person":
                breakdown_value, _ = get_property_string_expr("person", breakdown, "%(key)s", "person_props")
            elif self.filter.breakdown_type == "group":
                properties_field = f"group_properties_{self.filter.breakdown_group_type_index}"
                breakdown_value, _ = get_property_string_expr(
                    "groups",
                    breakdown,
                    "%(key)s",
                    properties_field,
                    materialised_table_column="group_properties",
                )
            else:
                breakdown_value, _ = get_property_string_expr("events", breakdown, "%(key)s", "properties")

        if self.filter.using_histogram:
            breakdown_value = f"toFloat64OrNull(toString({breakdown_value}))"

        breakdown_value = normalize_url_breakdown(breakdown_value, self.filter.breakdown_normalize_url)

        return breakdown_value

    def _get_histogram_breakdown_values(self, raw_breakdown_value: str, buckets: list[int]):
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
            breakdown_value = value.get("breakdown_value")
            breakdown_value = re.sub(r"\bnan\b", "NaN", breakdown_value)  # fix NaN values for JSON loading
            return json.loads(breakdown_value)[0]
        if value.get("breakdown_value") == "all":
            return (-1, "")
        if self.filter.breakdown_type == "session":
            # if session duration breakdown, we want ordering based on the time buckets, not the value
            return (-1, "")

        count_or_aggregated_value = value.get("count", value.get("aggregated_value") or 0)
        return count_or_aggregated_value * -1, value.get("label")  # reverse it

    def _parse_single_aggregate_result(
        self, filter: Filter, entity: Entity, additional_values: dict[str, Any]
    ) -> Callable:
        def _parse(result: list) -> list:
            parsed_results = []
            cache_invalidation_key = generate_short_id()
            for stats in result:
                aggregated_value = stats[0]
                result_descriptors = self._breakdown_result_descriptors(stats[1], filter, entity)
                filter_params = filter.to_params()
                extra_params = {
                    "entity_id": entity.id,
                    "entity_type": entity.type,
                    "entity_math": entity.math,
                    "breakdown_value": result_descriptors["breakdown_value"],
                    "breakdown_type": filter.breakdown_type or "event",
                }
                parsed_params: dict[str, str] = encode_get_request_params({**filter_params, **extra_params})
                parsed_result = {
                    "aggregated_value": (
                        float(correct_result_for_sampling(aggregated_value, filter.sampling_factor, entity.math))
                        if aggregated_value is not None
                        else None
                    ),
                    "filter": filter_params,
                    "persons": {
                        "filter": extra_params,
                        "url": f"api/projects/{self.team_id}/persons/trends/?{urllib.parse.urlencode(parsed_params)}&cache_invalidation_key={cache_invalidation_key}",
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
        def _parse(result: list) -> list:
            parsed_results = []
            for stats in result:
                result_descriptors = self._breakdown_result_descriptors(stats[2], filter, entity)
                parsed_result = parse_response(stats, filter, additional_values=result_descriptors, entity=entity)
                if self.add_person_urls:
                    parsed_result.update(
                        {
                            "persons_urls": self._get_persons_url(
                                filter,
                                entity,
                                self.team,
                                stats[0],
                                result_descriptors["breakdown_value"],
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
        self,
        filter: Filter,
        entity: Entity,
        team: Team,
        point_dates: list[datetime],
        breakdown_value: Union[str, int],
    ) -> list[dict[str, Any]]:
        persons_url = []
        cache_invalidation_key = generate_short_id()
        for point_date in point_dates:
            point_datetime = datetime(
                point_date.year,
                point_date.month,
                point_date.day,
                getattr(point_date, "hour", 0),
                getattr(point_date, "minute", 0),
                getattr(point_date, "second", 0),
                tzinfo=getattr(point_date, "tzinfo", ZoneInfo("UTC")),
            ).astimezone(ZoneInfo("UTC"))

            filter_params = filter.to_params()
            extra_params = {
                "entity_id": entity.id,
                "entity_type": entity.type,
                "entity_math": entity.math,
                "date_from": filter.date_from if filter.display == TRENDS_CUMULATIVE else point_datetime,
                "date_to": offset_time_series_date_by_interval(point_datetime, filter=filter, team=team),
                "breakdown_value": breakdown_value,
                "breakdown_type": filter.breakdown_type or "event",
            }
            parsed_params: dict[str, str] = encode_get_request_params({**filter_params, **extra_params})
            persons_url.append(
                {
                    "filter": extra_params,
                    "url": f"api/projects/{team.pk}/persons/trends/?{urllib.parse.urlencode(parsed_params)}&cache_invalidation_key={cache_invalidation_key}",
                }
            )
        return persons_url

    def _breakdown_result_descriptors(self, breakdown_value, filter: Filter, entity: Entity):
        extra_label = self._determine_breakdown_label(breakdown_value, filter.breakdown_type, breakdown_value)
        if len(filter.entities) > 1:
            # if there are multiple entities in the query, include the entity name in the labels
            label = "{} - {}".format(entity.name, extra_label)
        else:
            label = extra_label
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
        value: Union[str, int],
    ) -> str:
        if breakdown_type == "cohort":
            return get_breakdown_cohort_name(breakdown_value)
        elif str(value) == BREAKDOWN_OTHER_STRING_LABEL or value == BREAKDOWN_OTHER_NUMERIC_LABEL:
            return BREAKDOWN_OTHER_DISPLAY
        elif str(value) == BREAKDOWN_NULL_STRING_LABEL or value == BREAKDOWN_NULL_NUMERIC_LABEL:
            return BREAKDOWN_NULL_DISPLAY
        else:
            return str(value) or BREAKDOWN_NULL_DISPLAY

    def _person_join_condition(self) -> tuple[str, dict]:
        if self.person_on_events_mode == PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS:
            return "", {}

        if self.person_on_events_mode == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS:
            return (
                PERSON_DISTINCT_ID_OVERRIDES_JOIN_SQL.format(
                    person_overrides_table_alias=self.PERSON_ID_OVERRIDES_TABLE_ALIAS,
                    event_table_alias=self.EVENT_TABLE_ALIAS,
                ),
                {"team_id": self.team_id},
            )

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

    def _groups_join_condition(self) -> tuple[str, dict]:
        return GroupsJoinQuery(
            self.filter,
            self.team_id,
            self.column_optimizer,
            person_on_events_mode=self.person_on_events_mode,
        ).get_join_query()

    def _sessions_join_condition(self) -> tuple[str, dict]:
        session_query = SessionQuery(filter=self.filter, team=self.team)
        if session_query.is_used:
            query, session_params = session_query.get_query()
            return (
                f"""
                    INNER JOIN ({query}) {SessionQuery.SESSION_TABLE_ALIAS}
                    ON {SessionQuery.SESSION_TABLE_ALIAS}."$session_id" = e."$session_id"
                """,
                session_params,
            )
        return "", {}
