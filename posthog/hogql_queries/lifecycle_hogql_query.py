from typing import Optional

from django.utils.timezone import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr, action_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.models import Team, Action
from posthog.hogql_queries.query_date_range import QueryDateRange
from posthog.schema import LifecycleQuery, ActionsNode, EventsNode, LifecycleQueryResponse


def create_events_query(
    query_date_range: QueryDateRange,
    event_filter: Optional[ast.Expr],
    timings: HogQLTimings,
    sampling_factor: Optional[float] = None,
):
    placeholders = {
        "event_filter": event_filter or ast.Constant(value=True),
        "interval": query_date_range.interval_period_string_as_hogql_constant(),
        "one_interval_period": query_date_range.one_interval_period(),
    }

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
        placeholders=placeholders,
        timings=timings,
    )

    if sampling_factor is not None and isinstance(sampling_factor, float):
        sample_expr = ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=sampling_factor)))
        events_query.select_from.sample = sample_expr

    return events_query


def run_lifecycle_query(team: Team, query: LifecycleQuery) -> LifecycleQueryResponse:
    now_dt = datetime.now()
    timings = HogQLTimings()

    event_filter = []
    with timings.measure("date_range"):
        query_date_range = QueryDateRange(date_range=query.dateRange, team=team, interval=query.interval, now=now_dt)
        event_filter.append(
            parse_expr(
                "timestamp >= dateTrunc({interval}, {date_from}) - {one_interval}",
                {
                    "interval": query_date_range.interval_period_string_as_hogql_constant(),
                    "one_interval": query_date_range.one_interval_period(),
                    "date_from": query_date_range.date_from_as_hogql(),
                },
                timings=timings,
            )
        )
        event_filter.append(
            parse_expr(
                "timestamp < dateTrunc({interval}, {date_to}) + {one_interval}",
                {
                    "interval": query_date_range.interval_period_string_as_hogql_constant(),
                    "one_interval": query_date_range.one_interval_period(),
                    "date_to": query_date_range.date_to_as_hogql(),
                },
                timings=timings,
            )
        )

    with timings.measure("properties"):
        if query.properties is not None and query.properties != []:
            event_filter.append(property_to_expr(query.properties, team))

    with timings.measure("series_filters"):
        for serie in query.series or []:
            if isinstance(serie, ActionsNode):
                action = Action.objects.get(pk=int(serie.id), team=team)
                event_filter.append(action_to_expr(action))
            elif isinstance(serie, EventsNode):
                if serie.event is not None:
                    event_filter.append(
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["event"]),
                            right=ast.Constant(value=str(serie.event)),
                        )
                    )
            else:
                raise ValueError(f"Invalid serie kind: {serie.kind}")
            if serie.properties is not None and serie.properties != []:
                event_filter.append(property_to_expr(serie.properties, team))

    with timings.measure("test_account_filters"):
        if (
            query.filterTestAccounts
            and isinstance(team.test_account_filters, list)
            and len(team.test_account_filters) > 0
        ):
            for property in team.test_account_filters:
                event_filter.append(property_to_expr(property, team))

    if len(event_filter) == 0:
        event_filter = ast.Constant(value=True)
    elif len(event_filter) == 1:
        event_filter = event_filter[0]
    else:
        event_filter = ast.And(exprs=event_filter)

    placeholders = {
        "interval": query_date_range.interval_period_string_as_hogql_constant(),
        "one_interval_period": query_date_range.one_interval_period(),
        "number_interval_period": query_date_range.number_interval_periods(),
        "event_filter": event_filter,
        "date_from": query_date_range.date_from_as_hogql(),
        "date_to": query_date_range.date_to_as_hogql(),
    }

    with timings.measure("events_query"):
        events_query = create_events_query(
            query_date_range=query_date_range,
            event_filter=event_filter,
            sampling_factor=query.samplingFactor,
            timings=timings,
        )

    with timings.measure("periods_query"):
        periods = parse_select(
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
            placeholders=placeholders,
        )

    with timings.measure("lifecycle_query"):
        lifecycle_sql = parse_select(
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
                        FROM {periods} as periods
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
            {**placeholders, "periods": periods, "events_query": events_query},
        )

    response = execute_hogql_query(
        team=team,
        query=lifecycle_sql,
        query_type="LifecycleQuery",
    )

    # ensure that the items are in a deterministic order
    order = {"new": 1, "returning": 2, "resurrecting": 3, "dormant": 4}
    results = sorted(response.results, key=lambda result: order.get(result[2], 5))

    res = []
    for val in results:
        counts = val[1]
        labels = [
            item.strftime("%-d-%b-%Y{}".format(" %H:%M" if query_date_range.interval_name == "hour" else ""))
            for item in val[0]
        ]
        days = [
            item.strftime("%Y-%m-%d{}".format(" %H:%M:%S" if query_date_range.interval_name == "hour" else ""))
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

    return LifecycleQueryResponse(result=res, timings=response.timings)
