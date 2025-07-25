from datetime import timedelta, datetime
from math import ceil
from typing import Optional

from posthog.caching.insights_api import (
    BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL,
    REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.property import property_to_expr, action_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.timestamp_utils import format_label_date
from posthog.models import Action
from posthog.hogql_queries.utils.query_date_range import QueryDateRange, compare_interval_length
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    CachedLifecycleQueryResponse,
    LifecycleQuery,
    ActionsNode,
    EventsNode,
    LifecycleQueryResponse,
    InsightActorsQueryOptionsResponse,
    IntervalType,
    StatusItem,
    DayItem,
    ResolvedDateRangeResponse,
)


class LifecycleQueryRunner(QueryRunner):
    query: LifecycleQuery
    response: LifecycleQueryResponse
    cached_response: CachedLifecycleQueryResponse

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        if self.query.samplingFactor == 0:
            counts_with_sampling: ast.Expr = ast.Constant(value=0)
        elif self.query.samplingFactor is not None and self.query.samplingFactor != 1:
            counts_with_sampling = parse_expr(
                "round(counts * (1 / {sampling_factor}))",
                {
                    "sampling_factor": ast.Constant(value=self.query.samplingFactor),
                },
            )
        else:
            counts_with_sampling = parse_expr("counts")

        placeholders = {
            **self.query_date_range.to_placeholders(),
            "events_query": self.events_query,
            "periods_query": self.periods_query,
            "counts_with_sampling": counts_with_sampling,
        }
        with self.timings.measure("lifecycle_query"):
            lifecycle_query = parse_select(
                """
                    SELECT groupArray(start_of_period) AS date,
                           groupArray({counts_with_sampling}) AS total,
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
                                start_of_period, count(DISTINCT actor_id) AS counts, status
                            FROM {events_query}
                            GROUP BY start_of_period, status
                        )
                        WHERE start_of_period <= {date_to_start_of_interval}
                            AND start_of_period >= {date_from_start_of_interval}
                        GROUP BY start_of_period, status
                        ORDER BY start_of_period ASC
                    )
                    GROUP BY status
                """,
                placeholders,
                timings=self.timings,
            )
        return lifecycle_query

    def to_actors_query(
        self, day: Optional[str] = None, status: Optional[str] = None
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        with self.timings.measure("actors_query"):
            exprs: list[ast.Expr] = []
            if day is not None:
                exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["start_of_period"]),
                        right=self.query_date_range.date_to_start_of_interval_hogql(
                            ast.Call(name="toDateTime", args=[ast.Constant(value=day)])
                        ),
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
                "SELECT DISTINCT actor_id FROM {events_query} WHERE {where}",
                placeholders={
                    "events_query": self.events_query,
                    "where": ast.And(exprs=exprs) if len(exprs) > 0 else ast.Constant(value=1),
                },
            )

    def to_actors_query_options(self) -> InsightActorsQueryOptionsResponse:
        return InsightActorsQueryOptionsResponse(
            day=[
                DayItem(label=format_label_date(value, self.query_date_range, self.team.week_start_day), value=value)
                for value in self.query_date_range.all_values()
            ],
            status=[
                StatusItem(label="Dormant", value="dormant"),
                StatusItem(label="New", value="new"),
                StatusItem(label="Resurrecting", value="resurrecting"),
                StatusItem(label="Returning", value="returning"),
            ],
        )

    def calculate(self) -> LifecycleQueryResponse:
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team)

        response = execute_hogql_query(
            query_type="LifecycleQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        # TODO: can we move the data conversion part into the query as well? It would make it easier to swap
        # e.g. the LifecycleQuery with HogQLQuery, while keeping the chart logic the same.

        # ensure that the items are in a deterministic order
        order = {"new": 1, "returning": 2, "resurrecting": 3, "dormant": 4}
        results = sorted(response.results, key=lambda result: order.get(result[2], 5))

        res = []
        for val in results:
            counts = val[1]
            labels = [format_label_date(item, self.query_date_range, self.team.week_start_day) for item in val[0]]
            days = [
                item.strftime("%Y-%m-%d{}".format(" %H:%M:%S" if self.query_date_range.interval_name == "hour" else ""))
                for item in val[0]
            ]

            # legacy response compatibility object
            action_object = {}
            label = "{} - {}".format("", val[2])
            if isinstance(self.query.series[0], ActionsNode):
                action = Action.objects.get(pk=int(self.query.series[0].id), team__project_id=self.team.project_id)
                label = "{} - {}".format(action.name, val[2])
                action_object = {
                    "id": str(action.pk),
                    "name": action.name,
                    "type": "actions",
                    "order": 0,
                    "math": "total",
                }
            elif isinstance(self.query.series[0], EventsNode):
                event = self.query.series[0].event
                label = "{} - {}".format("All events" if event is None else event, val[2])
                action_object = {
                    "id": event,
                    "name": "All events" if event is None else event,
                    "type": "events",
                    "order": 0,
                    "math": "total",
                }

            additional_values = {"label": label, "status": val[2]}
            res.append(
                {
                    "action": action_object,
                    "data": [float(c) for c in counts],
                    "count": float(sum(counts)),
                    "labels": labels,
                    "days": days,
                    **additional_values,
                }
            )

        return LifecycleQueryResponse(
            results=res,
            timings=response.timings,
            hogql=hogql,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )

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
        event_filters: list[ast.Expr] = [
            ast.CompareOperation(
                left=ast.Field(chain=["properties", "$process_person_profile"]),
                right=ast.Constant(value="false"),
                op=ast.CompareOperationOp.NotEq,
            )
        ]
        with self.timings.measure("date_range"):
            event_filters.append(
                parse_expr(
                    "timestamp >= {date_from_start_of_interval} - {one_interval_period}",
                    self.query_date_range.to_placeholders(),
                    timings=self.timings,
                )
            )
            event_filters.append(
                parse_expr(
                    "timestamp < {date_to_start_of_interval} + {one_interval_period}",
                    self.query_date_range.to_placeholders(),
                    timings=self.timings,
                )
            )
        with self.timings.measure("properties"):
            if self.query.properties is not None and self.query.properties != []:
                event_filters.append(property_to_expr(self.query.properties, self.team))
        with self.timings.measure("series_filters"):
            for serie in self.query.series or []:
                if isinstance(serie, ActionsNode):
                    action = Action.objects.get(pk=int(serie.id), team__project_id=self.team.project_id)
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

        if self.has_group_type:
            event_filters.append(
                ast.Not(
                    expr=ast.Call(
                        name="has",
                        args=[
                            ast.Array(exprs=[ast.Constant(value="")]),
                            self.target_field,
                        ],
                    ),
                ),
            )

        if len(event_filters) == 0:
            return ast.Constant(value=True)
        elif len(event_filters) == 1:
            return event_filters[0]
        else:
            return ast.And(exprs=event_filters)

    @property
    def has_group_type(self) -> bool:
        return self.group_type_index is not None and 0 <= self.group_type_index <= 4

    @property
    def group_type_index(self) -> int | None:
        return self.query.aggregation_group_type_index

    @property
    def target_field(self):
        if self.has_group_type:
            return ast.Field(chain=["events", f"$group_{self.group_type_index}"])
        return ast.Field(chain=["person_id"])

    @cached_property
    def events_query(self):
        with self.timings.measure("events_query"):
            # :TRICKY: Timezone in clickhouse is represented as metadata on a column.
            # When we group the array, the timezone information is lost.
            # When DST changes, this causes an issue where after we add or subtract one_interval_period from the timestamp, we get a off by an hour error
            def timezone_wrapper(var: str) -> str:
                if compare_interval_length(self.query_date_range.interval_type, "<=", IntervalType.DAY):
                    return f"toTimeZone({var}, {{timezone}})"
                # Above DAY, toStartOfInterval turns the DateTimes into Dates, which no longer take timezones.
                return var

            events_query = parse_select(
                f"""
                    SELECT
                        min(events.person.created_at) AS created_at,
                        arraySort(groupUniqArray({{trunc_timestamp}})) AS all_activity,
                        arrayPopBack(arrayPushFront(all_activity, {{trunc_created_at}})) as previous_activity,
                        arrayPopFront(arrayPushBack(all_activity, {{trunc_epoch}})) as following_activity,
                        arrayMap((previous, current, index) -> (previous = current ? 'new' : (({timezone_wrapper('current')} - {{one_interval_period}}) = previous AND index != 1) ? 'returning' : 'resurrecting'), previous_activity, all_activity, arrayEnumerate(all_activity)) as initial_status,
                        arrayMap((current, next) -> ({timezone_wrapper('current')} + {{one_interval_period}} = {timezone_wrapper('next')} ? '' : 'dormant'), all_activity, following_activity) as dormant_status,
                        arrayMap(x -> {timezone_wrapper('x')} + {{one_interval_period}}, arrayFilter((current, is_dormant) -> is_dormant = 'dormant', all_activity, dormant_status)) as dormant_periods,
                        arrayMap(x -> 'dormant', dormant_periods) as dormant_label,
                        arrayConcat(arrayZip(all_activity, initial_status), arrayZip(dormant_periods, dormant_label)) as temp_concat,
                        arrayJoin(temp_concat) as period_status_pairs,
                        period_status_pairs.1 as start_of_period,
                        period_status_pairs.2 as status,
                        {{target}}
                    FROM events
                    WHERE {{event_filter}}
                    GROUP BY actor_id
                """,
                placeholders={
                    **self.query_date_range.to_placeholders(),
                    "target": ast.Alias(alias="actor_id", expr=self.target_field),
                    "event_filter": self.event_filter,
                    "trunc_timestamp": self.query_date_range.date_to_start_of_interval_hogql(
                        ast.Field(chain=["events", "timestamp"])
                    ),
                    "trunc_created_at": self.query_date_range.date_to_start_of_interval_hogql(
                        ast.Field(chain=["created_at"])
                    ),
                    "trunc_epoch": self.query_date_range.date_to_start_of_interval_hogql(
                        ast.Call(name="toDateTime", args=[ast.Constant(value="1970-01-01 00:00:00")])
                    ),
                    "timezone": ast.Constant(value=self.team.timezone),
                },
                timings=self.timings,
            )
            assert isinstance(events_query, ast.SelectQuery)
            sampling_factor = self.query.samplingFactor
            if sampling_factor is not None and isinstance(sampling_factor, float) and events_query.select_from:
                sample_expr = ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=sampling_factor)))
                events_query.select_from.sample = sample_expr

        return events_query

    @cached_property
    def periods_query(self):
        with self.timings.measure("periods_query"):
            periods_query = parse_select(
                """
                    SELECT ({date_to_start_of_interval} - {number_interval_period}) AS start_of_period
                    FROM numbers(dateDiff({interval}, {date_from_start_of_interval}, {date_to_plus_interval}))
                """,
                placeholders={
                    **self.query_date_range.to_placeholders(),
                    "date_to_plus_interval": self.query_date_range.date_to_start_of_interval_hogql(
                        parse_expr(
                            "{date_to} + {one_interval_period}", placeholders=self.query_date_range.to_placeholders()
                        )
                    ),
                },
                timings=self.timings,
            )
        return periods_query

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
