from typing import Any, Dict, Literal, Optional, Tuple, Union, cast

from ee.clickhouse.models.group import get_aggregation_target_field
from ee.clickhouse.models.property import get_single_or_multi_property_string_expr
from ee.clickhouse.queries.event_query import EnterpriseEventQuery
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
from posthog.models.team import Team
from posthog.queries.util import get_trunc_func_ch


class RetentionEventsQuery(EnterpriseEventQuery):
    _filter: RetentionFilter
    _event_query_type: RetentionQueryType
    _trunc_func: str

    def __init__(
        self,
        filter: RetentionFilter,
        event_query_type: RetentionQueryType,
        team: Team,
        aggregate_users_by_distinct_id: Optional[bool] = None,
    ):
        self._event_query_type = event_query_type
        super().__init__(
            filter=filter, team=team, override_aggregate_users_by_distinct_id=aggregate_users_by_distinct_id
        )

        self._trunc_func = get_trunc_func_ch(self._filter.period)

    def get_query(self) -> Tuple[str, Dict[str, Any]]:

        _fields = [
            self.get_timestamp_field(),
            (
                f"argMin(e.uuid, {self._trunc_func}(toDateTime(e.timestamp, %(timezone)s))) as min_uuid"
                if self._event_query_type == RetentionQueryType.TARGET_FIRST_TIME
                else f"{self.EVENT_TABLE_ALIAS}.uuid AS uuid"
            ),
            (
                f"argMin(e.event, {self._trunc_func}(toDateTime(e.timestamp, %(timezone)s))) as min_event"
                if self._event_query_type == RetentionQueryType.TARGET_FIRST_TIME
                else f"{self.EVENT_TABLE_ALIAS}.event AS event"
            ),
        ]

        if self._aggregate_users_by_distinct_id and not self._filter.aggregation_group_type_index:
            _fields += [f"{self.EVENT_TABLE_ALIAS}.distinct_id as target"]
        else:
            _fields += [
                "{} as target".format(
                    get_aggregation_target_field(
                        self._filter.aggregation_group_type_index,
                        self.EVENT_TABLE_ALIAS,
                        f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id",
                    )
                )
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

            if breakdown_type == "person":
                table = "person"

            breakdown_values_expression = get_single_or_multi_property_string_expr(
                breakdown=[breakdown["property"] for breakdown in self._filter.breakdowns],
                table=cast(Union[Literal["events"], Literal["person"]], table),
                query_alias=None,
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
            if self._event_query_type == RetentionQueryType.TARGET_FIRST_TIME:
                _fields += [
                    f"""
                    [
                        dateDiff(
                            %(period)s,
                            {self._trunc_func}(toDateTime(%(start_date)s)),
                            {self._trunc_func}(min(e.timestamp))
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
                            {self._trunc_func}(toDateTime(%(start_date)s)),
                            {self._trunc_func}(e.timestamp)
                        )
                    ] as breakdown_values
                    """
                ]
            self.params.update({"start_date": self._filter.date_from, "period": self._filter.period})

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        prop_query, prop_params = self._get_prop_groups(self._filter.property_groups)

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

        query = f"""
            SELECT {','.join(_fields)} FROM events {self.EVENT_TABLE_ALIAS}
            {self._get_distinct_id_query()}
            {person_query}
            {groups_query}
            WHERE team_id = %(team_id)s
            {f"AND {entity_query}"}
            {f"AND {date_query}" if self._event_query_type != RetentionQueryType.TARGET_FIRST_TIME else ''}
            {prop_query}
            {f"GROUP BY target HAVING {date_query}" if self._event_query_type == RetentionQueryType.TARGET_FIRST_TIME else ''}
        """

        return query, self.params

    def get_timestamp_field(self) -> str:
        if self._event_query_type == RetentionQueryType.TARGET:
            return f"DISTINCT {self._trunc_func}(toDateTime({self.EVENT_TABLE_ALIAS}.timestamp, %(timezone)s)) AS event_date"
        elif self._event_query_type == RetentionQueryType.TARGET_FIRST_TIME:
            return f"min({self._trunc_func}(toDateTime(e.timestamp, %(timezone)s))) as event_date"
        else:
            return f"{self._trunc_func}(toDateTime({self.EVENT_TABLE_ALIAS}.timestamp, %(timezone)s)) AS event_date"

    def _determine_should_join_distinct_ids(self) -> None:
        if self._filter.aggregation_group_type_index is not None or self._aggregate_users_by_distinct_id:
            self._should_join_distinct_ids = False
        else:
            self._should_join_distinct_ids = True

    def _get_entity_query(self, entity: Entity):
        prepend = self._event_query_type
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=entity.id)
            action_query, params = format_action_filter(
                team_id=self._team_id, action=action, prepend=prepend, use_loop=False
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
            else f"toDateTime({self.EVENT_TABLE_ALIAS}.timestamp) >= toDateTime(%({self._event_query_type}_start_date)s, %(timezone)s) AND toDateTime({self.EVENT_TABLE_ALIAS}.timestamp) <= toDateTime(%({self._event_query_type}_end_date)s, %(timezone)s)"
        )
        params = {
            f"{self._event_query_type}_start_date": self._filter.date_from.strftime(
                "%Y-%m-%d{}".format(" %H:%M:%S" if self._filter.period == "Hour" else " 00:00:00")
            ),
            f"{self._event_query_type}_end_date": (
                (self._filter.date_from + self._filter.period_increment)
                if self._filter.display == TRENDS_LINEAR and self._event_query_type == RetentionQueryType.TARGET
                else self._filter.date_to
            ).strftime("%Y-%m-%d{}".format(" %H:%M:%S" if self._filter.period == "Hour" else " 00:00:00")),
        }
        return query, params
