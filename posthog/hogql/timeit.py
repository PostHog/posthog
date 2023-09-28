from hogql_parser import parse_expr as parse_expr_fast
from .parser import parse_expr
import timeit

# TODO: Remove before merging the C++-based parser

TEST_SELECT = """SELECT groupArray(start_of_period) AS date,
    groupArray(counts) AS total,
    status
FROM (
        SELECT if(
                equals(status, 'dormant'),
                negate(sum(counts)),
                negate(negate(sum(counts)))
            ) AS counts,
            start_of_period,
            status
        FROM (
                SELECT periods.start_of_period AS start_of_period,
                    0 AS counts,
                    status
                FROM (
                        SELECT
                        minus
(
                            dateTrunc(
                                'day',
                                assumeNotNull(toDateTime('2023-09-20 23:59:59'))
                            ),
                            toIntervalDay(number)
                        ) AS start_of_period
                        FROM numbers(
                                dateDiff(
                                    'day',
                                    dateTrunc(
                                        'day',
                                        assumeNotNull(toDateTime('2023-09-13 00:00:00'))
                                    ),
                                    dateTrunc(
                                        'day',
                                        plus(
                                            assumeNotNull(toDateTime('2023-09-20 23:59:59')),
                                            toIntervalDay(1)
                                        )
                                    )
                                )
                            ) AS numbers
                    ) AS periods
                    CROSS JOIN (
                        SELECT status
                        FROM (
                                SELECT 1
                            ) ARRAY
                            JOIN ['new', 'returning', 'resurrecting', 'dormant'] AS status
                    ) AS sec
                ORDER BY status ASC,
                    start_of_period ASC
                UNION ALL
                SELECT start_of_period,
                    count(DISTINCT person_id) AS counts,
                    status
                FROM (
                        SELECT events.person.id AS person_id,
                            min(events.person.created_at) AS created_at,
                            arraySort(
                                groupUniqArray(dateTrunc('day', events.timestamp))
                            ) AS all_activity,
                            arrayPopBack(
                                arrayPushFront(all_activity, dateTrunc('day', created_at))
                            ) AS previous_activity,
                            arrayPopFront(
                                arrayPushBack(
                                    all_activity,
                                    dateTrunc('day', toDateTime('1970-01-01 00:00:00'))
                                )
                            ) AS following_activity,
                            arrayMap(
                                (previous, current, index)->if(
                                    equals(previous, current),
                                    'new',
                                    if(
                                        and(
                                            equals(
                                            minus
(current, toIntervalDay(1)), previous),
                                            notEquals(index, 1)
                                        ),
                                        'returning',
                                        'resurrecting'
                                    )
                                ),
                                previous_activity,
                                all_activity,
                                arrayEnumerate(all_activity)
                            ) AS initial_status,
                            arrayMap(
                                (current, next)->if(
                                    equals(plus(current, toIntervalDay(1)), next),
                                    '',
                                    'dormant'
                                ),
                                all_activity,
                                following_activity
                            ) AS dormant_status,
                            arrayMap(
                                x->plus(x, toIntervalDay(1)),
                                arrayFilter(
                                    (current, is_dormant)->equals(is_dormant, 'dormant'),
                                    all_activity,
                                    dormant_status
                                )
                            ) AS dormant_periods,
                            arrayMap(x->'dormant', dormant_periods) AS dormant_label,
                            arrayConcat(
                                arrayZip(all_activity, initial_status),
                                arrayZip(dormant_periods, dormant_label)
                            ) AS temp_concat,
                            arrayJoin(temp_concat) AS period_status_pairs,
                            period_status_pairs.1 AS start_of_period,
                            period_status_pairs.2 AS status
                        FROM events
                        WHERE
                            and(
                                greaterOrEquals(
                                    timestamp,
                                    minus
(
                                        dateTrunc(
                                            'day',
                                            assumeNotNull(toDateTime('2023-09-13 00:00:00'))
                                        ),
                                        toIntervalDay(1)
                                    )
                                ),
                                less(
                                    timestamp,
                                    plus(
                                        dateTrunc(
                                            'day',
                                            assumeNotNull(toDateTime('2023-09-20 23:59:59'))
                                        ),
                                        toIntervalDay(1)
                                    )
                                ),
                                equals(event, '$pageview'),
                                in(
                                    person_id,
                                    (
                                        SELECT person_id
                                        FROM cohort_people
                                        WHERE equals(cohort_id, 2)
                                        GROUP BY person_id,
                                            cohort_id,
                                            version
                                        HAVING greater(sum(sign), 0)
                                    )
                                )
                            )
                        GROUP BY person_id
                    )
                GROUP BY start_of_period,
                    status
            )
        WHERE
            and(
                lessOrEquals(
                    start_of_period,
                    dateTrunc(
                        'day',
                        assumeNotNull(toDateTime('2023-09-20 23:59:59'))
                    )
                ),
                greaterOrEquals(
                    start_of_period,
                    dateTrunc(
                        'day',
                        assumeNotNull(toDateTime('2023-09-13 00:00:00'))
                    )
                )
            )
        GROUP BY start_of_period,
            status
        ORDER BY start_of_period ASC
    )
GROUP BY status
LIMIT 10000"""
TEST_SELECT_SIMPLE = """SELECT
    step1.distinct_id AS user_id,
    step1.timestamp AS pageview_timestamp,
    step2.timestamp AS signup_timestamp,
    step3.timestamp AS purchase_timestamp
FROM
(
    SELECT
        distinct_id,
        timestamp
    FROM
        events
    WHERE
        event = '$pageview'
        AND timestamp >= now() - INTERVAL 30 DAY
) AS step1
INNER JOIN
(
    SELECT
        distinct_id,
        timestamp
    FROM
        events
    WHERE
        event = 'signup'
        AND timestamp >= now() - INTERVAL 30 DAY
) AS step2 ON step1.distinct_id = step2.distinct_id
INNER JOIN
(
    SELECT
        distinct_id,
        timestamp
    FROM
        events
    WHERE
        event = 'purchase'
        AND timestamp >= now() - INTERVAL 30 DAY
) AS step3 ON step2.distinct_id = step3.distinct_id
    AND step3.timestamp >= step2.timestamp
    AND step3.timestamp <= step2.timestamp + INTERVAL 7 DAY
ORDER BY
    user_id, pageview_timestamp, signup_timestamp, purchase_timestamp"""

TEST_EXPR_SIMPLE = "TRUE = 2"

N_SIMPLE = 10000
N_COMPLEX = 10


cpp_timing = timeit.timeit(lambda: parse_expr_fast(TEST_EXPR_SIMPLE), number=N_SIMPLE)
print(f"{cpp_timing:.3f} s for expr `{TEST_EXPR_SIMPLE}` {N_SIMPLE}x in C++")  # noqa: T201
python_timing = timeit.timeit(lambda: parse_expr(TEST_EXPR_SIMPLE), number=N_SIMPLE)
print(f"{python_timing:.3f} s for expr `{TEST_EXPR_SIMPLE}` {N_SIMPLE}x in Python")  # noqa: T201
