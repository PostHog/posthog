from typing import Any, Dict, Literal, Optional, Tuple, Union, cast

from posthog.constants import (
    PAGEVIEW_EVENT,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
    TRENDS_LINEAR,
    RetentionQueryType,
)
from posthog.models import Entity
from posthog.models.action.util import Action, format_action_filter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.property.util import get_single_or_multi_property_string_expr
from posthog.models.team import Team
from posthog.models.utils import PersonPropertiesMode
from posthog.queries.event_query import EventQuery
from posthog.queries.query_date_range import QueryDateRange
from posthog.queries.util import get_trunc_func_ch


class RetentionEventsQuery(EventQuery):
    _filter: RetentionFilter
    _event_query_type: RetentionQueryType
    _trunc_func: str

    def __init__(
        self,
        filter: RetentionFilter,
        event_query_type: RetentionQueryType,
        team: Team,
        aggregate_users_by_distinct_id: Optional[bool] = None,
        using_person_on_events: bool = False,
    ):
        self._event_query_type = event_query_type
        super().__init__(
            filter=filter,
            team=team,
            override_aggregate_users_by_distinct_id=aggregate_users_by_distinct_id,
            using_person_on_events=using_person_on_events,
        )

        self._trunc_func = get_trunc_func_ch(self._filter.period)

    def get_query(self) -> Tuple[str, Dict[str, Any]]:

        _fields = [
            self.get_timestamp_field(),
            self.target_field(),
        ]

        if self._filter.breakdowns and self._filter.breakdown_type:
            # NOTE: `get_single_or_multi_property_string_expr` doesn't
            # support breakdowns with different types e.g. a person property
            # then an event property, so for now we just take the type of
            # the self._filter.breakdown_type.
            # TODO: update 'get_single_or_multi_property_string_expr` to take
            # `Breakdown` type
            breakdown_type = self._filter.breakdown_type
            table = "events"
            column = "properties"
            materalised_table_column = "properties"

            if breakdown_type == "person":
                table = "person" if not self._using_person_on_events else "events"
                column = "person_props" if not self._using_person_on_events else "person_properties"
                materalised_table_column = "properties" if not self._using_person_on_events else "person_properties"

            breakdown_values_expression = get_single_or_multi_property_string_expr(
                breakdown=[breakdown["property"] for breakdown in self._filter.breakdowns],
                table=cast(Union[Literal["events"], Literal["person"]], table),
                query_alias=None,
                column=column,
                materialised_table_column=materalised_table_column,
            )

            if self._event_query_type == RetentionQueryType.TARGET_FIRST_TIME:
                _fields += [f"argMin({breakdown_values_expression}, e.timestamp) AS breakdown_values"]
            else:
                _fields += [f"{breakdown_values_expression} AS breakdown_values"]
        else:
            # If we didn't have a breakdown specified, we default to the
            # initial event interval
            # NOTE: we wrap as an array to maintain the same structure as
            # for typical breakdowns
            # NOTE: we could add support for specifying expressions to
            # `get_single_or_multi_property_string_expr` or an abstraction
            # over the top somehow
            # NOTE: we use the datediff rather than the date to make our
            # lives easier when zero filling the response. We could however
            # handle this WITH FILL within the query.

            start_of_week_day = QueryDateRange.determine_extra_trunc_func_args(self._trunc_func)
            if self._event_query_type == RetentionQueryType.TARGET_FIRST_TIME:
                _fields += [
                    f"""
                    [
                        dateDiff(
                            %(period)s,
                            {self._trunc_func}(toDateTime(%(start_date)s {start_of_week_day}, %(timezone)s)),
                            {self._trunc_func}(min(toTimeZone(toDateTime(e.timestamp, 'UTC'), %(timezone)s)))
                        )
                    ] as breakdown_values
                    """
                ]
            elif self._event_query_type == RetentionQueryType.TARGET:
                _fields += [
                    f"""
                    [
                        dateDiff(
                            %(period)s,
                            {self._trunc_func}(toDateTime(%(start_date)s {start_of_week_day}, %(timezone)s)),
                            {self._trunc_func}(toTimeZone(toDateTime(e.timestamp, 'UTC'), %(timezone)s))
                        )
                    ] as breakdown_values
                    """
                ]
            self.params.update({"start_date": self._filter.date_from, "period": self._filter.period})

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        prop_query, prop_params = self._get_prop_groups(
            self._filter.property_groups,
            person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS
            if self._using_person_on_events
            else PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
            person_id_joined_alias=f"{self.EVENT_TABLE_ALIAS if self._using_person_on_events else self.DISTINCT_ID_TABLE_ALIAS}.person_id",
        )

        self.params.update(prop_params)

        entity_query, entity_params = self._get_entity_query(
            entity=self._filter.target_entity
            if self._event_query_type == RetentionQueryType.TARGET
            or self._event_query_type == RetentionQueryType.TARGET_FIRST_TIME
            else self._filter.returning_entity
        )
        self.params.update(entity_params)

        person_query, person_params = self._get_person_query()
        self.params.update(person_params)

        groups_query, groups_params = self._get_groups_query()
        self.params.update(groups_params)

        null_person_filter = f"AND notEmpty({self.EVENT_TABLE_ALIAS}.person_id)" if self._using_person_on_events else ""

        sample_clause = f"SAMPLE {self._filter.sampling_factor}" if self._filter.sampling_factor else ""

        query = f"""
            SELECT {','.join(_fields)} FROM events {self.EVENT_TABLE_ALIAS}
            {sample_clause}
            {self._get_distinct_id_query()}
            {person_query}
            {groups_query}
            WHERE team_id = %(team_id)s
            {f"AND {entity_query}"}
            {f"AND {date_query}" if self._event_query_type != RetentionQueryType.TARGET_FIRST_TIME else ''}
            {prop_query}
            {null_person_filter}
            {f"GROUP BY target HAVING {date_query}" if self._event_query_type == RetentionQueryType.TARGET_FIRST_TIME else ''}
            {f"GROUP BY target, event_date" if self._event_query_type == RetentionQueryType.RETURNING else ''}
        """

        return query, self.params

    def target_field(self) -> str:
        if self._aggregate_users_by_distinct_id and not self._filter.aggregation_group_type_index:
            return f"{self.EVENT_TABLE_ALIAS}.distinct_id as target"
        else:
            return "{} as target".format(
                f"{self.DISTINCT_ID_TABLE_ALIAS if not self._using_person_on_events else self.EVENT_TABLE_ALIAS}.person_id"
            )

    def get_timestamp_field(self) -> str:
        start_of_week_day = QueryDateRange.determine_extra_trunc_func_args(self._trunc_func)
        if self._event_query_type == RetentionQueryType.TARGET:
            return f"DISTINCT {self._trunc_func}(toDateTime({self.EVENT_TABLE_ALIAS}.timestamp) {start_of_week_day}, %(timezone)s) AS event_date"
        elif self._event_query_type == RetentionQueryType.TARGET_FIRST_TIME:
            return f"min({self._trunc_func}(toTimeZone(toDateTime(e.timestamp, 'UTC'), %(timezone)s))) as event_date"
        else:
            return f"{self._trunc_func}(toTimeZone(toDateTime({self.EVENT_TABLE_ALIAS}.timestamp, 'UTC'), %(timezone)s)) AS event_date"

    def _determine_should_join_distinct_ids(self) -> None:
        if (
            self._filter.aggregation_group_type_index is not None or self._aggregate_users_by_distinct_id
        ) and not self._column_optimizer.is_using_cohort_propertes:
            self._should_join_distinct_ids = False
        else:
            self._should_join_distinct_ids = True

    def _determine_should_join_persons(self) -> None:
        EventQuery._determine_should_join_persons(self)
        if self._using_person_on_events:
            self._should_join_distinct_ids = False
            self._should_join_persons = False

    def _get_entity_query(self, entity: Entity):
        prepend = self._event_query_type
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=entity.id)
            action_query, params = format_action_filter(
                team_id=self._team_id,
                action=action,
                prepend=prepend,
                use_loop=False,
                person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS
                if self._using_person_on_events
                else PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
                person_id_joined_alias=f"{self.DISTINCT_ID_TABLE_ALIAS if not self._using_person_on_events else self.EVENT_TABLE_ALIAS}.person_id",
                hogql_context=self._filter.hogql_context,
            )
            condition = action_query
        elif entity.type == TREND_FILTER_TYPE_EVENTS:
            condition = f"{self.EVENT_TABLE_ALIAS}.event = %({prepend}_event)s"
            params = {f"{prepend}_event": entity.id}
        else:
            condition = f"{self.EVENT_TABLE_ALIAS}.event = %({prepend}_event)s"
            params = {f"{prepend}_event": PAGEVIEW_EVENT}
        return condition, params

    def _get_date_filter(self):
        query = (
            f"event_date >= toDateTime(%({self._event_query_type}_start_date)s, %(timezone)s) AND event_date <= toDateTime(%({self._event_query_type}_end_date)s, %(timezone)s)"
            if self._event_query_type == RetentionQueryType.TARGET_FIRST_TIME
            else f"toDateTime({self.EVENT_TABLE_ALIAS}.timestamp) >= toDateTime(%({self._event_query_type}_start_date)s,  %(timezone)s) AND toDateTime({self.EVENT_TABLE_ALIAS}.timestamp) <= toDateTime(%({self._event_query_type}_end_date)s, %(timezone)s)"
        )
        start_date = self._filter.date_from
        end_date = (
            (self._filter.date_from + self._filter.period_increment)
            if self._filter.display == TRENDS_LINEAR and self._event_query_type == RetentionQueryType.TARGET
            else self._filter.date_to
        )
        if self._filter.period != "Hour":
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
        params = {
            f"{self._event_query_type}_start_date": start_date.strftime("%Y-%m-%d %H:%M:%S"),
            f"{self._event_query_type}_end_date": end_date.strftime("%Y-%m-%d %H:%M:%S"),
        }
        return query, params
