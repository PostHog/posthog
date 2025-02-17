# Support for using a data warehouse table inside of a Funnels experiment

We'd like funnel experiments to support the data warehouse similar to how trends experiments do.

The `breakdownAttributionType` has these potential values:

-   `last_touch`
-   `first_touch`
-   `all_events`
-   `step`

## Example queries

### First step attribution

```sql
SELECT
    sum(step_1) AS step_1,
    sum(step_2) AS step_2,
    sum(step_3) AS step_3,
    if(isNaN(avgArrayOrNull(step_1_conversion_time_array) AS inter_1_conversion), NULL, inter_1_conversion) AS step_1_average_conversion_time,
    if(isNaN(avgArrayOrNull(step_2_conversion_time_array) AS inter_2_conversion), NULL, inter_2_conversion) AS step_2_average_conversion_time,
    if(isNaN(medianArrayOrNull(step_1_conversion_time_array) AS inter_1_median), NULL, inter_1_median) AS step_1_median_conversion_time,
    if(isNaN(medianArrayOrNull(step_2_conversion_time_array) AS inter_2_median), NULL, inter_2_median) AS step_2_median_conversion_time,
    if(ifNull(less(row_number, 26), 0), prop, ['Other']) AS final_prop
FROM
    (SELECT
        countIf(ifNull(equals(steps, 1), 0)) AS step_1,
        countIf(ifNull(equals(steps, 2), 0)) AS step_2,
        countIf(ifNull(equals(steps, 3), 0)) AS step_3,
        groupArray(step_1_conversion_time) AS step_1_conversion_time_array,
        groupArray(step_2_conversion_time) AS step_2_conversion_time_array,
        prop AS prop,
        row_number() OVER (ORDER BY step_3 DESC) AS row_number
    FROM
        (SELECT
            aggregation_target AS aggregation_target,
            steps AS steps,
            prop AS prop,
            prop AS prop,
            min(step_1_conversion_time) AS step_1_conversion_time,
            min(step_2_conversion_time) AS step_2_conversion_time
        FROM
            (SELECT
                aggregation_target AS aggregation_target,
                steps AS steps,
                prop AS prop,
                max(steps) OVER (PARTITION BY aggregation_target, prop) AS max_steps,
                step_1_conversion_time AS step_1_conversion_time,
                step_2_conversion_time AS step_2_conversion_time,
                prop AS prop
            FROM
                (SELECT
                    aggregation_target AS aggregation_target,
                    timestamp AS timestamp,
                    step_0 AS step_0,
                    latest_0 AS latest_0,
                    step_1 AS step_1,
                    latest_1 AS latest_1,
                    step_2 AS step_2,
                    latest_2 AS latest_2,
                    prop AS prop,
                    if(and(ifNull(lessOrEquals(latest_0, latest_1), 0), ifNull(lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14))), 0), ifNull(lessOrEquals(latest_1, latest_2), 0), ifNull(lessOrEquals(latest_2, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14))), 0)), 3, if(and(ifNull(lessOrEquals(latest_0, latest_1), 0), ifNull(lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14))), 0)), 2, 1)) AS steps,
                    if(and(isNotNull(latest_1), ifNull(lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14))), 0)), dateDiff('second', latest_0, latest_1), NULL) AS step_1_conversion_time,
                    if(and(isNotNull(latest_2), ifNull(lessOrEquals(latest_2, plus(toTimeZone(latest_1, 'UTC'), toIntervalDay(14))), 0)), dateDiff('second', latest_1, latest_2), NULL) AS step_2_conversion_time,
                    prop AS prop
                FROM
                    (SELECT
                        aggregation_target AS aggregation_target,
                        timestamp AS timestamp,
                        step_0 AS step_0,
                        latest_0 AS latest_0,
                        step_1 AS step_1,
                        latest_1 AS latest_1,
                        step_2 AS step_2,
                        min(latest_2) OVER (PARTITION BY aggregation_target, prop ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 0 PRECEDING) AS latest_2,
                        prop AS prop
                    FROM
                        (SELECT
                            aggregation_target AS aggregation_target,
                            timestamp AS timestamp,
                            step_0 AS step_0,
                            latest_0 AS latest_0,
                            step_1 AS step_1,
                            latest_1 AS latest_1,
                            step_2 AS step_2,
                            if(ifNull(less(latest_2, latest_1), 0), NULL, latest_2) AS latest_2,
                            prop AS prop
                        FROM
                            (SELECT
                                aggregation_target AS aggregation_target,
                                timestamp AS timestamp,
                                step_0 AS step_0,
                                latest_0 AS latest_0,
                                step_1 AS step_1,
                                min(latest_1) OVER (PARTITION BY aggregation_target, prop ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 0 PRECEDING) AS latest_1,
                                step_2 AS step_2,
                                min(latest_2) OVER (PARTITION BY aggregation_target, prop ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 0 PRECEDING) AS latest_2,
                                prop AS prop
                            FROM
                                (SELECT
                                    timestamp AS timestamp,
                                    aggregation_target AS aggregation_target,
                                    step_0 AS step_0,
                                    latest_0 AS latest_0,
                                    step_1 AS step_1,
                                    latest_1 AS latest_1,
                                    step_2 AS step_2,
                                    latest_2 AS latest_2,
                                    prop_basic AS prop_basic,
                                    prop,
                                    prop_vals AS prop_vals,
                                    if(notEmpty(arrayFilter(x -> notEmpty(x), prop_vals)), prop_vals, ['']) AS prop
                                FROM
                                    (SELECT
                                        toTimeZone(e.timestamp, 'UTC') AS timestamp,
                                        if(not(empty(e__override.distinct_id)), e__override.person_id, e.person_id) AS aggregation_target,
                                        if(equals(e.event, 'seen'), 1, 0) AS step_0,
                                        if(ifNull(equals(step_0, 1), 0), timestamp, NULL) AS latest_0,
                                        if(equals(e.event, 'signup'), 1, 0) AS step_1,
                                        if(ifNull(equals(step_1, 1), 0), timestamp, NULL) AS latest_1,
                                        if(equals(e.event, 'purchase'), 1, 0) AS step_2,
                                        if(ifNull(equals(step_2, 1), 0), timestamp, NULL) AS latest_2,
                                        [ifNull(toString(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(e.properties, '$feature/test-experiment'), ''), 'null'), '^"|"$', '')), '')] AS prop_basic,
                                        prop_basic AS prop,
                                        argMinIf(prop, timestamp, notEmpty(arrayFilter(x -> notEmpty(x), prop))) OVER (PARTITION BY aggregation_target) AS prop_vals
                                    FROM
                                        events AS e
                                        LEFT OUTER JOIN (SELECT
                                            argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
                                            person_distinct_id_overrides.distinct_id AS distinct_id
                                        FROM
                                            person_distinct_id_overrides
                                        WHERE
                                            equals(person_distinct_id_overrides.team_id, 3570)
                                        GROUP BY
                                            person_distinct_id_overrides.distinct_id
                                        HAVING
                                            ifNull(equals(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version), 0), 0)
                                        SETTINGS optimize_aggregation_in_order=1) AS e__override ON equals(e.distinct_id, e__override.distinct_id)
                                    WHERE
                                        and(equals(e.team_id, 3570), and(and(greaterOrEquals(toTimeZone(e.timestamp, 'UTC'), toDateTime64('2020-01-01 00:00:00.000000', 6, 'UTC')), lessOrEquals(toTimeZone(e.timestamp, 'UTC'), toDateTime64('2020-01-15 00:00:00.000000', 6, 'UTC'))), in(e.event, tuple('purchase', 'seen', 'signup'))), or(ifNull(equals(step_0, 1), 0), ifNull(equals(step_1, 1), 0), ifNull(equals(step_2, 1), 0))))))))
                WHERE
                    ifNull(equals(step_0, 1), 0)))
        GROUP BY
            aggregation_target,
            steps,
            prop
        HAVING
            ifNull(equals(steps, max(max_steps)), isNull(steps) and isNull(max(max_steps))))
    GROUP BY
        prop)
GROUP BY
    final_prop
```

### Last step attribution

```sql
SELECT
    sum(step_1) AS step_1,
    sum(step_2) AS step_2,
    sum(step_3) AS step_3,
    if(isNaN(avgArrayOrNull(step_1_conversion_time_array) AS inter_1_conversion), NULL, inter_1_conversion) AS step_1_average_conversion_time,
    if(isNaN(avgArrayOrNull(step_2_conversion_time_array) AS inter_2_conversion), NULL, inter_2_conversion) AS step_2_average_conversion_time,
    if(isNaN(medianArrayOrNull(step_1_conversion_time_array) AS inter_1_median), NULL, inter_1_median) AS step_1_median_conversion_time,
    if(isNaN(medianArrayOrNull(step_2_conversion_time_array) AS inter_2_median), NULL, inter_2_median) AS step_2_median_conversion_time,
    if(ifNull(less(row_number, 26), 0), prop, ['Other']) AS final_prop
FROM
    (SELECT
        countIf(ifNull(equals(steps, 1), 0)) AS step_1,
        countIf(ifNull(equals(steps, 2), 0)) AS step_2,
        countIf(ifNull(equals(steps, 3), 0)) AS step_3,
        groupArray(step_1_conversion_time) AS step_1_conversion_time_array,
        groupArray(step_2_conversion_time) AS step_2_conversion_time_array,
        prop AS prop,
        row_number() OVER (ORDER BY step_3 DESC) AS row_number
    FROM
        (SELECT
            aggregation_target AS aggregation_target,
            steps AS steps,
            prop AS prop,
            prop AS prop,
            min(step_1_conversion_time) AS step_1_conversion_time,
            min(step_2_conversion_time) AS step_2_conversion_time
        FROM
            (SELECT
                aggregation_target AS aggregation_target,
                steps AS steps,
                prop AS prop,
                max(steps) OVER (PARTITION BY aggregation_target, prop) AS max_steps,
                step_1_conversion_time AS step_1_conversion_time,
                step_2_conversion_time AS step_2_conversion_time,
                prop AS prop
            FROM
                (SELECT
                    aggregation_target AS aggregation_target,
                    timestamp AS timestamp,
                    step_0 AS step_0,
                    latest_0 AS latest_0,
                    step_1 AS step_1,
                    latest_1 AS latest_1,
                    step_2 AS step_2,
                    latest_2 AS latest_2,
                    prop AS prop,
                    if(and(ifNull(lessOrEquals(latest_0, latest_1), 0), ifNull(lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14))), 0), ifNull(lessOrEquals(latest_1, latest_2), 0), ifNull(lessOrEquals(latest_2, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14))), 0)), 3, if(and(ifNull(lessOrEquals(latest_0, latest_1), 0), ifNull(lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14))), 0)), 2, 1)) AS steps,
                    if(and(isNotNull(latest_1), ifNull(lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14))), 0)), dateDiff('second', latest_0, latest_1), NULL) AS step_1_conversion_time,
                    if(and(isNotNull(latest_2), ifNull(lessOrEquals(latest_2, plus(toTimeZone(latest_1, 'UTC'), toIntervalDay(14))), 0)), dateDiff('second', latest_1, latest_2), NULL) AS step_2_conversion_time,
                    prop AS prop
                FROM
                    (SELECT
                        aggregation_target AS aggregation_target,
                        timestamp AS timestamp,
                        step_0 AS step_0,
                        latest_0 AS latest_0,
                        step_1 AS step_1,
                        latest_1 AS latest_1,
                        step_2 AS step_2,
                        min(latest_2) OVER (PARTITION BY aggregation_target, prop ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 0 PRECEDING) AS latest_2,
                        prop AS prop
                    FROM
                        (SELECT
                            aggregation_target AS aggregation_target,
                            timestamp AS timestamp,
                            step_0 AS step_0,
                            latest_0 AS latest_0,
                            step_1 AS step_1,
                            latest_1 AS latest_1,
                            step_2 AS step_2,
                            if(ifNull(less(latest_2, latest_1), 0), NULL, latest_2) AS latest_2,
                            prop AS prop
                        FROM
                            (SELECT
                                aggregation_target AS aggregation_target,
                                timestamp AS timestamp,
                                step_0 AS step_0,
                                latest_0 AS latest_0,
                                step_1 AS step_1,
                                min(latest_1) OVER (PARTITION BY aggregation_target, prop ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 0 PRECEDING) AS latest_1,
                                step_2 AS step_2,
                                min(latest_2) OVER (PARTITION BY aggregation_target, prop ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 0 PRECEDING) AS latest_2,
                                prop AS prop
                            FROM
                                (SELECT
                                    timestamp AS timestamp,
                                    aggregation_target AS aggregation_target,
                                    step_0 AS step_0,
                                    latest_0 AS latest_0,
                                    step_1 AS step_1,
                                    latest_1 AS latest_1,
                                    step_2 AS step_2,
                                    latest_2 AS latest_2,
                                    prop_basic AS prop_basic,
                                    prop,
                                    prop_vals AS prop_vals,
                                    if(notEmpty(arrayFilter(x -> notEmpty(x), prop_vals)), prop_vals, ['']) AS prop
                                FROM
                                    (SELECT
                                        toTimeZone(e.timestamp, 'UTC') AS timestamp,
                                        if(not(empty(e__override.distinct_id)), e__override.person_id, e.person_id) AS aggregation_target,
                                        if(equals(e.event, 'seen'), 1, 0) AS step_0,
                                        if(ifNull(equals(step_0, 1), 0), timestamp, NULL) AS latest_0,
                                        if(equals(e.event, 'signup'), 1, 0) AS step_1,
                                        if(ifNull(equals(step_1, 1), 0), timestamp, NULL) AS latest_1,
                                        if(equals(e.event, 'purchase'), 1, 0) AS step_2,
                                        if(ifNull(equals(step_2, 1), 0), timestamp, NULL) AS latest_2,
                                        [ifNull(toString(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(e.properties, '$feature/test-experiment'), ''), 'null'), '^"|"$', '')), '')] AS prop_basic,
                                        prop_basic AS prop,
                                        argMaxIf(prop, timestamp, notEmpty(arrayFilter(x -> notEmpty(x), prop))) OVER (PARTITION BY aggregation_target) AS prop_vals
                                    FROM
                                        events AS e
                                        LEFT OUTER JOIN (SELECT
                                            argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
                                            person_distinct_id_overrides.distinct_id AS distinct_id
                                        FROM
                                            person_distinct_id_overrides
                                        WHERE
                                            equals(person_distinct_id_overrides.team_id, 3571)
                                        GROUP BY
                                            person_distinct_id_overrides.distinct_id
                                        HAVING
                                            ifNull(equals(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version), 0), 0)
                                        SETTINGS optimize_aggregation_in_order=1) AS e__override ON equals(e.distinct_id, e__override.distinct_id)
                                    WHERE
                                        and(equals(e.team_id, 3571), and(and(greaterOrEquals(toTimeZone(e.timestamp, 'UTC'), toDateTime64('2020-01-01 00:00:00.000000', 6, 'UTC')), lessOrEquals(toTimeZone(e.timestamp, 'UTC'), toDateTime64('2020-01-15 00:00:00.000000', 6, 'UTC'))), in(e.event, tuple('purchase', 'seen', 'signup'))), or(ifNull(equals(step_0, 1), 0), ifNull(equals(step_1, 1), 0), ifNull(equals(step_2, 1), 0))))))))
                WHERE
                    ifNull(equals(step_0, 1), 0)))
        GROUP BY
            aggregation_target,
            steps,
            prop
        HAVING
            ifNull(equals(steps, max(max_steps)), isNull(steps) and isNull(max(max_steps))))
    GROUP BY
        prop)
GROUP BY
    final_prop
```

### All events attribution

```sql
SELECT
    sum(step_1) AS step_1,
    sum(step_2) AS step_2,
    sum(step_3) AS step_3,
    if(isNaN(avgArrayOrNull(step_1_conversion_time_array) AS inter_1_conversion), NULL, inter_1_conversion) AS step_1_average_conversion_time,
    if(isNaN(avgArrayOrNull(step_2_conversion_time_array) AS inter_2_conversion), NULL, inter_2_conversion) AS step_2_average_conversion_time,
    if(isNaN(medianArrayOrNull(step_1_conversion_time_array) AS inter_1_median), NULL, inter_1_median) AS step_1_median_conversion_time,
    if(isNaN(medianArrayOrNull(step_2_conversion_time_array) AS inter_2_median), NULL, inter_2_median) AS step_2_median_conversion_time,
    if(ifNull(less(row_number, 26), 0), prop, ['Other']) AS final_prop
FROM
    (SELECT
        countIf(ifNull(equals(steps, 1), 0)) AS step_1,
        countIf(ifNull(equals(steps, 2), 0)) AS step_2,
        countIf(ifNull(equals(steps, 3), 0)) AS step_3,
        groupArray(step_1_conversion_time) AS step_1_conversion_time_array,
        groupArray(step_2_conversion_time) AS step_2_conversion_time_array,
        prop AS prop,
        row_number() OVER (ORDER BY step_3 DESC) AS row_number
    FROM
        (SELECT
            aggregation_target AS aggregation_target,
            steps AS steps,
            prop AS prop,
            prop AS prop,
            min(step_1_conversion_time) AS step_1_conversion_time,
            min(step_2_conversion_time) AS step_2_conversion_time
        FROM
            (SELECT
                aggregation_target AS aggregation_target,
                steps AS steps,
                prop AS prop,
                max(steps) OVER (PARTITION BY aggregation_target, prop) AS max_steps,
                step_1_conversion_time AS step_1_conversion_time,
                step_2_conversion_time AS step_2_conversion_time,
                prop AS prop
            FROM
                (SELECT
                    aggregation_target AS aggregation_target,
                    timestamp AS timestamp,
                    step_0 AS step_0,
                    latest_0 AS latest_0,
                    step_1 AS step_1,
                    latest_1 AS latest_1,
                    step_2 AS step_2,
                    latest_2 AS latest_2,
                    prop AS prop,
                    if(and(ifNull(lessOrEquals(latest_0, latest_1), 0), ifNull(lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14))), 0), ifNull(lessOrEquals(latest_1, latest_2), 0), ifNull(lessOrEquals(latest_2, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14))), 0)), 3, if(and(ifNull(lessOrEquals(latest_0, latest_1), 0), ifNull(lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14))), 0)), 2, 1)) AS steps,
                    if(and(isNotNull(latest_1), ifNull(lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14))), 0)), dateDiff('second', latest_0, latest_1), NULL) AS step_1_conversion_time,
                    if(and(isNotNull(latest_2), ifNull(lessOrEquals(latest_2, plus(toTimeZone(latest_1, 'UTC'), toIntervalDay(14))), 0)), dateDiff('second', latest_1, latest_2), NULL) AS step_2_conversion_time,
                    prop AS prop
                FROM
                    (SELECT
                        aggregation_target AS aggregation_target,
                        timestamp AS timestamp,
                        step_0 AS step_0,
                        latest_0 AS latest_0,
                        step_1 AS step_1,
                        latest_1 AS latest_1,
                        step_2 AS step_2,
                        min(latest_2) OVER (PARTITION BY aggregation_target, prop ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 0 PRECEDING) AS latest_2,
                        prop AS prop
                    FROM
                        (SELECT
                            aggregation_target AS aggregation_target,
                            timestamp AS timestamp,
                            step_0 AS step_0,
                            latest_0 AS latest_0,
                            step_1 AS step_1,
                            latest_1 AS latest_1,
                            step_2 AS step_2,
                            if(ifNull(less(latest_2, latest_1), 0), NULL, latest_2) AS latest_2,
                            prop AS prop
                        FROM
                            (SELECT
                                aggregation_target AS aggregation_target,
                                timestamp AS timestamp,
                                step_0 AS step_0,
                                latest_0 AS latest_0,
                                step_1 AS step_1,
                                min(latest_1) OVER (PARTITION BY aggregation_target, prop ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 0 PRECEDING) AS latest_1,
                                step_2 AS step_2,
                                min(latest_2) OVER (PARTITION BY aggregation_target, prop ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 0 PRECEDING) AS latest_2,
                                prop AS prop
                            FROM
                                (SELECT
                                    toTimeZone(e.timestamp, 'UTC') AS timestamp,
                                    if(not(empty(e__override.distinct_id)), e__override.person_id, e.person_id) AS aggregation_target,
                                    if(equals(e.event, 'seen'), 1, 0) AS step_0,
                                    if(ifNull(equals(step_0, 1), 0), timestamp, NULL) AS latest_0,
                                    if(equals(e.event, 'signup'), 1, 0) AS step_1,
                                    if(ifNull(equals(step_1, 1), 0), timestamp, NULL) AS latest_1,
                                    if(equals(e.event, 'purchase'), 1, 0) AS step_2,
                                    if(ifNull(equals(step_2, 1), 0), timestamp, NULL) AS latest_2,
                                    [ifNull(toString(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(e.properties, '$feature/test-experiment'), ''), 'null'), '^"|"$', '')), '')] AS prop_basic,
                                    prop_basic AS prop
                                FROM
                                    events AS e
                                    LEFT OUTER JOIN (SELECT
                                        argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
                                        person_distinct_id_overrides.distinct_id AS distinct_id
                                    FROM
                                        person_distinct_id_overrides
                                    WHERE
                                        equals(person_distinct_id_overrides.team_id, 3588)
                                    GROUP BY
                                        person_distinct_id_overrides.distinct_id
                                    HAVING
                                        ifNull(equals(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version), 0), 0)
                                    SETTINGS optimize_aggregation_in_order=1) AS e__override ON equals(e.distinct_id, e__override.distinct_id)
                                WHERE
                                    and(equals(e.team_id, 3588), and(and(greaterOrEquals(toTimeZone(e.timestamp, 'UTC'), toDateTime64('2020-01-01 00:00:00.000000', 6, 'UTC')), lessOrEquals(toTimeZone(e.timestamp, 'UTC'), toDateTime64('2020-01-15 00:00:00.000000', 6, 'UTC'))), in(e.event, tuple('purchase', 'seen', 'signup'))), or(ifNull(equals(step_0, 1), 0), ifNull(equals(step_1, 1), 0), ifNull(equals(step_2, 1), 0)))))))
                WHERE
                    ifNull(equals(step_0, 1), 0)))
        GROUP BY
            aggregation_target,
            steps,
            prop
        HAVING
            ifNull(equals(steps, max(max_steps)), isNull(steps) and isNull(max(max_steps))))
    GROUP BY
        prop)
GROUP BY
    final_prop
```

### Step attribution

```sql
SELECT
    sum(step_1) AS step_1,
    sum(step_2) AS step_2,
    sum(step_3) AS step_3,
    if(isNaN(avgArrayOrNull(step_1_conversion_time_array) AS inter_1_conversion), NULL, inter_1_conversion) AS step_1_average_conversion_time,
    if(isNaN(avgArrayOrNull(step_2_conversion_time_array) AS inter_2_conversion), NULL, inter_2_conversion) AS step_2_average_conversion_time,
    if(isNaN(medianArrayOrNull(step_1_conversion_time_array) AS inter_1_median), NULL, inter_1_median) AS step_1_median_conversion_time,
    if(isNaN(medianArrayOrNull(step_2_conversion_time_array) AS inter_2_median), NULL, inter_2_median) AS step_2_median_conversion_time,
    if(ifNull(less(row_number, 26), 0), prop, ['Other']) AS final_prop
FROM
    (SELECT
        countIf(ifNull(equals(steps, 1), 0)) AS step_1,
        countIf(ifNull(equals(steps, 2), 0)) AS step_2,
        countIf(ifNull(equals(steps, 3), 0)) AS step_3,
        groupArray(step_1_conversion_time) AS step_1_conversion_time_array,
        groupArray(step_2_conversion_time) AS step_2_conversion_time_array,
        prop AS prop,
        row_number() OVER (ORDER BY step_3 DESC) AS row_number
    FROM
        (SELECT
            aggregation_target AS aggregation_target,
            steps AS steps,
            prop AS prop,
            prop AS prop,
            min(step_1_conversion_time) AS step_1_conversion_time,
            min(step_2_conversion_time) AS step_2_conversion_time
        FROM
            (SELECT
                aggregation_target AS aggregation_target,
                steps AS steps,
                prop AS prop,
                max(steps) OVER (PARTITION BY aggregation_target, prop) AS max_steps,
                step_1_conversion_time AS step_1_conversion_time,
                step_2_conversion_time AS step_2_conversion_time,
                prop AS prop
            FROM
                (SELECT
                    aggregation_target AS aggregation_target,
                    timestamp AS timestamp,
                    step_0 AS step_0,
                    latest_0 AS latest_0,
                    step_1 AS step_1,
                    latest_1 AS latest_1,
                    step_2 AS step_2,
                    latest_2 AS latest_2,
                    prop AS prop,
                    if(and(ifNull(lessOrEquals(latest_0, latest_1), 0), ifNull(lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14))), 0), ifNull(lessOrEquals(latest_1, latest_2), 0), ifNull(lessOrEquals(latest_2, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14))), 0)), 3, if(and(ifNull(lessOrEquals(latest_0, latest_1), 0), ifNull(lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14))), 0)), 2, 1)) AS steps,
                    if(and(isNotNull(latest_1), ifNull(lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14))), 0)), dateDiff('second', latest_0, latest_1), NULL) AS step_1_conversion_time,
                    if(and(isNotNull(latest_2), ifNull(lessOrEquals(latest_2, plus(toTimeZone(latest_1, 'UTC'), toIntervalDay(14))), 0)), dateDiff('second', latest_1, latest_2), NULL) AS step_2_conversion_time,
                    prop AS prop
                FROM
                    (SELECT
                        aggregation_target AS aggregation_target,
                        timestamp AS timestamp,
                        step_0 AS step_0,
                        latest_0 AS latest_0,
                        step_1 AS step_1,
                        latest_1 AS latest_1,
                        step_2 AS step_2,
                        min(latest_2) OVER (PARTITION BY aggregation_target, prop ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 0 PRECEDING) AS latest_2,
                        prop AS prop
                    FROM
                        (SELECT
                            aggregation_target AS aggregation_target,
                            timestamp AS timestamp,
                            step_0 AS step_0,
                            latest_0 AS latest_0,
                            step_1 AS step_1,
                            latest_1 AS latest_1,
                            step_2 AS step_2,
                            if(ifNull(less(latest_2, latest_1), 0), NULL, latest_2) AS latest_2,
                            prop AS prop
                        FROM
                            (SELECT
                                aggregation_target AS aggregation_target,
                                timestamp AS timestamp,
                                step_0 AS step_0,
                                latest_0 AS latest_0,
                                step_1 AS step_1,
                                min(latest_1) OVER (PARTITION BY aggregation_target, prop ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 0 PRECEDING) AS latest_1,
                                step_2 AS step_2,
                                min(latest_2) OVER (PARTITION BY aggregation_target, prop ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 0 PRECEDING) AS latest_2,
                                prop AS prop
                            FROM
                                (SELECT
                                    timestamp AS timestamp,
                                    aggregation_target AS aggregation_target,
                                    step_0 AS step_0,
                                    latest_0 AS latest_0,
                                    step_1 AS step_1,
                                    latest_1 AS latest_1,
                                    step_2 AS step_2,
                                    latest_2 AS latest_2,
                                    prop_basic AS prop_basic,
                                    prop_0 AS prop_0,
                                    prop_1 AS prop_1,
                                    prop_2 AS prop_2,
                                    prop,
                                    prop_vals AS prop_vals,
                                    prop
                                FROM
                                    (SELECT
                                        toTimeZone(e.timestamp, 'UTC') AS timestamp,
                                        if(not(empty(e__override.distinct_id)), e__override.person_id, e.person_id) AS aggregation_target,
                                        if(equals(e.event, 'seen'), 1, 0) AS step_0,
                                        if(ifNull(equals(step_0, 1), 0), timestamp, NULL) AS latest_0,
                                        if(equals(e.event, 'signup'), 1, 0) AS step_1,
                                        if(ifNull(equals(step_1, 1), 0), timestamp, NULL) AS latest_1,
                                        if(equals(e.event, 'purchase'), 1, 0) AS step_2,
                                        if(ifNull(equals(step_2, 1), 0), timestamp, NULL) AS latest_2,
                                        [ifNull(toString(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(e.properties, '$feature/test-experiment'), ''), 'null'), '^"|"$', '')), '')] AS prop_basic,
                                        if(ifNull(equals(step_0, 1), 0), prop_basic, []) AS prop_0,
                                        if(ifNull(equals(step_1, 1), 0), prop_basic, []) AS prop_1,
                                        if(ifNull(equals(step_2, 1), 0), prop_basic, []) AS prop_2,
                                        prop_1 AS prop,
                                        groupUniqArray(prop) OVER (PARTITION BY aggregation_target) AS prop_vals
                                    FROM
                                        events AS e
                                        LEFT OUTER JOIN (SELECT
                                            argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
                                            person_distinct_id_overrides.distinct_id AS distinct_id
                                        FROM
                                            person_distinct_id_overrides
                                        WHERE
                                            equals(person_distinct_id_overrides.team_id, 3585)
                                        GROUP BY
                                            person_distinct_id_overrides.distinct_id
                                        HAVING
                                            ifNull(equals(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version), 0), 0)
                                        SETTINGS optimize_aggregation_in_order=1) AS e__override ON equals(e.distinct_id, e__override.distinct_id)
                                    WHERE
                                        and(equals(e.team_id, 3585), and(and(greaterOrEquals(toTimeZone(e.timestamp, 'UTC'), toDateTime64('2020-01-01 00:00:00.000000', 6, 'UTC')), lessOrEquals(toTimeZone(e.timestamp, 'UTC'), toDateTime64('2020-01-15 00:00:00.000000', 6, 'UTC'))), in(e.event, tuple('purchase', 'seen', 'signup'))), or(ifNull(equals(step_0, 1), 0), ifNull(equals(step_1, 1), 0), ifNull(equals(step_2, 1), 0))))
                                ARRAY JOIN prop_vals AS prop
                                WHERE
                                    ifNull(notEquals(prop, []), isNotNull(prop) or isNotNull([]))))))
                WHERE
                    ifNull(equals(step_0, 1), 0)))
        GROUP BY
            aggregation_target,
            steps,
            prop
        HAVING
            ifNull(equals(steps, max(max_steps)), isNull(steps) and isNull(max(max_steps))))
    GROUP BY
        prop)
GROUP BY
    final_prop
```
