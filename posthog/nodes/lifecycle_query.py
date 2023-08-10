from typing import Dict, Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.models import Team
from posthog.schema import LifecycleQuery


def run_lifecycle_query(
    team: Team,
    query: LifecycleQuery,
) -> Dict[str, Any]:
    interval = query.interval.name or "day"
    if interval not in ["minute", "hour", "day", "week", "month", "quarter", "year"]:
        raise ValueError(f"Invalid interval: {interval}")
    one_interval_period = parse_expr(f"toInterval{interval.capitalize()}(1)")
    number_interval_period = parse_expr(f"toInterval{interval.capitalize()}(number)")
    date_from = parse_expr("assumeNotNull(toDateTime('2023-08-02 00:00:00'))")
    date_to = parse_expr("assumeNotNull(toDateTime('2023-08-09 23:59:59'))")
    time_filter = parse_expr(
        "timestamp >= {date_from} and timestamp < {date_to}", {"date_from": date_from, "date_to": date_to}
    )
    event_filter = time_filter  # TODO: add all other filters

    placeholders = {
        "interval": ast.Constant(value=interval),
        "one_interval_period": one_interval_period,
        "number_interval_period": number_interval_period,
        "event_filter": event_filter,
        "date_from": date_from,
        "date_to": date_to,
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
    )

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

    res = []
    for val in response.results:
        counts = val[1]
        labels = [item.strftime("%-d-%b-%Y{}".format(" %H:%M" if interval == "hour" else "")) for item in val[0]]
        days = [item.strftime("%Y-%m-%d{}".format(" %H:%M:%S" if interval == "hour" else "")) for item in val[0]]

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
        # parsed_result = parse_response(val, filter, additional_values=additional_values, entity=entity)
        # res.append(parsed_result)

    return {"result": res}

    # LIFECYCLE_EVENTS_QUERY = """
    # SELECT
    # ...
    # FROM events AS {event_table_alias}
    # {sample_clause} // "sample 1,2"
    #
    # WHERE team_id = %(team_id)s
    # {entity_filter}
    # {entity_prop_query}
    # {date_query}
    # {prop_query}
    #
    # {null_person_filter}
    # GROUP BY {person_column}
    # """
    # return query_result
