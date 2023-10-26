from datetime import timedelta
from math import ceil
from typing import Optional, Any, Dict, List

from django.utils.timezone import datetime
from posthog.caching.insights_api import (
    BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL,
    REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL,
)
from posthog.caching.utils import is_stale

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.property import property_to_expr, action_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.models import Team, Action
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    LifecycleQuery,
    ActionsNode,
    EventsNode,
    LifecycleQueryResponse,
)


class LifecycleQueryRunner(QueryRunner):
    query: LifecycleQuery
    query_type = LifecycleQuery

    def __init__(
        self,
        query: LifecycleQuery | Dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        in_export_context: Optional[bool] = False,
    ):
        super().__init__(query, team, timings, in_export_context)

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        placeholders = {
            **self.query_date_range.to_placeholders(),
            "events_query": self.events_query,
            "periods_query": self.periods_query,
        }
        with self.timings.measure("lifecycle_query"):
            lifecycle_query = parse_select(
                """
                    SELECT groupArray(start_of_period) AS date,
                           groupArray(counts) AS total,
                           status
                    FROM (
                        SELECT
                            status = 'dormant' ? negate(sum(counts)) : negate(negate(sum(counts))) as counts,
                            start_of_period,
                            status
                        FROM (
                            SELECT
                                periods.start_of_period as start_of_period,
                                0 AS counts,
                                status
                            FROM {periods_query} as periods
                            CROSS JOIN (
                                SELECT status
                                FROM (SELECT 1)
                                ARRAY JOIN ['new', 'returning', 'resurrecting', 'dormant'] as status
                            ) as sec
                            ORDER BY status, start_of_period
                            UNION ALL
                            SELECT
                                start_of_period, count(DISTINCT person_id) AS counts, status
                            FROM {events_query}
                            GROUP BY start_of_period, status
                        )
                        WHERE start_of_period <= dateTrunc({interval}, {date_to})
                            AND start_of_period >= dateTrunc({interval}, {date_from})
                        GROUP BY start_of_period, status
                        ORDER BY start_of_period ASC
                    )
                    GROUP BY status
                """,
                placeholders,
                timings=self.timings,
            )
        return lifecycle_query

    def to_persons_query(
        self, day: Optional[str] = None, status: Optional[str] = None
    ) -> ast.SelectQuery | ast.SelectUnionQuery:
        with self.timings.measure("persons_query"):
            exprs = []
            if day is not None:
                exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["start_of_period"]),
                        right=ast.Constant(value=day),
                    )
                )
            if status is not None:
                exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["status"]),
                        right=ast.Constant(value=status),
                    )
                )

            return parse_select(
                "SELECT person_id FROM {events_query} WHERE {where}",
                placeholders={
                    "events_query": self.events_query,
                    "where": ast.And(exprs=exprs) if len(exprs) > 0 else ast.Constant(value=1),
                },
            )

    def calculate(self):
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team.pk)

        response = execute_hogql_query(
            query_type="LifecycleQuery",
            query=query,
            team=self.team,
            timings=self.timings,
        )

        # TODO: can we move the data conversion part into the query as well? It would make it easier to swap
        # e.g. the LifecycleQuery with HogQLQuery, while keeping the chart logic the same.

        # ensure that the items are in a deterministic order
        order = {"new": 1, "returning": 2, "resurrecting": 3, "dormant": 4}
        results = sorted(response.results, key=lambda result: order.get(result[2], 5))

        res = []
        for val in results:
            counts = val[1]
            labels = [
                item.strftime("%-d-%b-%Y{}".format(" %H:%M" if self.query_date_range.interval_name == "hour" else ""))
                for item in val[0]
            ]
            days = [
                item.strftime("%Y-%m-%d{}".format(" %H:%M:%S" if self.query_date_range.interval_name == "hour" else ""))
                for item in val[0]
            ]

            label = "{} - {}".format("", val[2])  # entity.name
            additional_values = {"label": label, "status": val[2]}
            res.append(
                {
                    "data": [float(c) for c in counts],
                    "count": float(sum(counts)),
                    "labels": labels,
                    "days": days,
                    **additional_values,
                }
            )

        return LifecycleQueryResponse(results=res, timings=response.timings, hogql=hogql)

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=self.query.interval,
            now=datetime.now(),
        )

    @cached_property
    def event_filter(self) -> ast.Expr:
        event_filters: List[ast.Expr] = []
        with self.timings.measure("date_range"):
            event_filters.append(
                parse_expr(
                    "timestamp >= dateTrunc({interval}, {date_from}) - {one_interval}",
                    {
                        "interval": self.query_date_range.interval_period_string_as_hogql_constant(),
                        "one_interval": self.query_date_range.one_interval_period(),
                        "date_from": self.query_date_range.date_from_as_hogql(),
                    },
                    timings=self.timings,
                )
            )
            event_filters.append(
                parse_expr(
                    "timestamp < dateTrunc({interval}, {date_to}) + {one_interval}",
                    {
                        "interval": self.query_date_range.interval_period_string_as_hogql_constant(),
                        "one_interval": self.query_date_range.one_interval_period(),
                        "date_to": self.query_date_range.date_to_as_hogql(),
                    },
                    timings=self.timings,
                )
            )
        with self.timings.measure("properties"):
            if self.query.properties is not None and self.query.properties != []:
                event_filters.append(property_to_expr(self.query.properties, self.team))
        with self.timings.measure("series_filters"):
            for serie in self.query.series or []:
                if isinstance(serie, ActionsNode):
                    action = Action.objects.get(pk=int(serie.id), team=self.team)
                    event_filters.append(action_to_expr(action))
                elif isinstance(serie, EventsNode):
                    if serie.event is not None:
                        event_filters.append(
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Eq,
                                left=ast.Field(chain=["event"]),
                                right=ast.Constant(value=str(serie.event)),
                            )
                        )
                else:
                    raise ValueError(f"Invalid serie kind: {serie.kind}")
                if serie.properties is not None and serie.properties != []:
                    event_filters.append(property_to_expr(serie.properties, self.team))
        with self.timings.measure("test_account_filters"):
            if (
                self.query.filterTestAccounts
                and isinstance(self.team.test_account_filters, list)
                and len(self.team.test_account_filters) > 0
            ):
                for property in self.team.test_account_filters:
                    event_filters.append(property_to_expr(property, self.team))

        if len(event_filters) == 0:
            return ast.Constant(value=True)
        elif len(event_filters) == 1:
            return event_filters[0]
        else:
            return ast.And(exprs=event_filters)

    @cached_property
    def events_query(self):
        with self.timings.measure("events_query"):
            events_query = parse_select(
                """
                    SELECT
                        events.person.id as person_id,
                        min(events.person.created_at) AS created_at,
                        arraySort(groupUniqArray(dateTrunc({interval}, events.timestamp))) AS all_activity,
                        arrayPopBack(arrayPushFront(all_activity, dateTrunc({interval}, created_at))) as previous_activity,
                        arrayPopFront(arrayPushBack(all_activity, dateTrunc({interval}, toDateTime('1970-01-01 00:00:00')))) as following_activity,
                        arrayMap((previous, current, index) -> (previous = current ? 'new' : ((current - {one_interval_period}) = previous AND index != 1) ? 'returning' : 'resurrecting'), previous_activity, all_activity, arrayEnumerate(all_activity)) as initial_status,
                        arrayMap((current, next) -> (current + {one_interval_period} = next ? '' : 'dormant'), all_activity, following_activity) as dormant_status,
                        arrayMap(x -> x + {one_interval_period}, arrayFilter((current, is_dormant) -> is_dormant = 'dormant', all_activity, dormant_status)) as dormant_periods,
                        arrayMap(x -> 'dormant', dormant_periods) as dormant_label,
                        arrayConcat(arrayZip(all_activity, initial_status), arrayZip(dormant_periods, dormant_label)) as temp_concat,
                        arrayJoin(temp_concat) as period_status_pairs,
                        period_status_pairs.1 as start_of_period,
                        period_status_pairs.2 as status
                    FROM events
                    WHERE {event_filter}
                    GROUP BY person_id
                """,
                placeholders={
                    **self.query_date_range.to_placeholders(),
                    "event_filter": self.event_filter,
                },
                timings=self.timings,
            )
            sampling_factor = self.query.samplingFactor
            if sampling_factor is not None and isinstance(sampling_factor, float):
                sample_expr = ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=sampling_factor)))
                events_query.select_from.sample = sample_expr

        return events_query

    @cached_property
    def periods_query(self):
        with self.timings.measure("periods_query"):
            periods_query = parse_select(
                """
                    SELECT (
                        dateTrunc({interval}, {date_to}) - {number_interval_period}
                    ) AS start_of_period
                    FROM numbers(
                        dateDiff(
                            {interval},
                            dateTrunc({interval}, {date_from}),
                            dateTrunc({interval}, {date_to} + {one_interval_period})
                        )
                    )
                """,
                placeholders=self.query_date_range.to_placeholders(),
                timings=self.timings,
            )
        return periods_query

    def _is_stale(self, cached_result_package):
        date_to = self.query_date_range.date_to()
        interval = self.query_date_range.interval_name
        return is_stale(self.team, date_to, interval, cached_result_package)

    def _refresh_frequency(self):
        date_to = self.query_date_range.date_to()
        date_from = self.query_date_range.date_from()
        interval = self.query_date_range.interval_name

        delta_days: Optional[int] = None
        if date_from and date_to:
            delta = date_to - date_from
            delta_days = ceil(delta.total_seconds() / timedelta(days=1).total_seconds())

        refresh_frequency = BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL
        if interval == "hour" or (delta_days is not None and delta_days <= 7):
            # The interval is shorter for short-term insights
            refresh_frequency = REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL

        return refresh_frequency
