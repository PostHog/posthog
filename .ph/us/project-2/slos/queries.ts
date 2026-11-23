import { heredoc } from '../shared/heredoc'

export type Region = 'us' | 'eu'

// Where each region's data lives in project 2's warehouse.
const tables: Record<Region, { exports: string; history: string }> = {
    us: { exports: 'postgres.posthog_exportedasset', history: 'system.cohort_calculation_history' },
    eu: { exports: 'eu_posthog_exportedasset', history: 'eu_posthog_cohortcalculationhistory' },
}

// Burn rates over 1, 7 and 30 days, from a daily query that returns (date, total, failures).
export function burnRateQuery(daily: string, errorBudget: number): string {
    return heredoc`
        WITH
            date_range AS (SELECT toDate(now()) - number AS date FROM numbers(30)),
            daily AS (
                ${daily}
            ),
            base AS (
                SELECT
                    d.date,
                    coalesce(daily.total, 0)    AS total,
                    coalesce(daily.failures, 0) AS failures
                FROM date_range d
                LEFT JOIN daily ON d.date = daily.date
            ),
            rolling AS (
                SELECT
                    date,
                    sum(failures) OVER w1  AS f1,  sum(total) OVER w1  AS t1,
                    sum(failures) OVER w7  AS f7,  sum(total) OVER w7  AS t7,
                    sum(failures) OVER w30 AS f30, sum(total) OVER w30 AS t30
                FROM base
                WINDOW
                    w1  AS (ORDER BY date ASC ROWS BETWEEN 0 PRECEDING AND CURRENT ROW),
                    w7  AS (ORDER BY date ASC ROWS BETWEEN 6 PRECEDING AND CURRENT ROW),
                    w30 AS (ORDER BY date ASC ROWS BETWEEN 29 PRECEDING AND CURRENT ROW)
            )
        SELECT date, metric, value
        FROM (
            SELECT
                date,
                ['Burn rate 1d', 'Burn rate 7d', 'Burn rate 30d'] AS metrics,
                [
                    round(if(t1  > 0, f1  / t1  / ${errorBudget}, 0), 2),
                    round(if(t7  > 0, f7  / t7  / ${errorBudget}, 0), 2),
                    round(if(t30 > 0, f30 / t30 / ${errorBudget}, 0), 2)
                ] AS values
            FROM rolling
        )
        ARRAY JOIN metrics AS metric, values AS value
        ORDER BY date ASC, metric ASC
        LIMIT 500
    `
}

// The CTEs for one SLO's 30-day success rate inside the combined query.
function successCte(prefix: string, daily: string): string {
    return heredoc`
        ${prefix}_daily AS (
            ${daily}
        ),
        ${prefix}_base AS (
            SELECT
                d.date,
                coalesce(daily.total, 0)    AS total,
                coalesce(daily.failures, 0) AS failures
            FROM date_range d
            LEFT JOIN ${prefix}_daily AS daily ON d.date = daily.date
        ),
        ${prefix}_rolling AS (
            SELECT
                date,
                sum(failures) OVER w AS f30,
                sum(total) OVER w    AS t30
            FROM ${prefix}_base
            WINDOW w AS (ORDER BY date ASC ROWS BETWEEN 29 PRECEDING AND CURRENT ROW)
        )
    `
}

function successSelect(prefix: string, name: string): string {
    return heredoc`
        SELECT date, '${name}' AS slo,
               round(if(t30 > 0, (t30 - f30) / t30 * 100, 0), 2) AS value
        FROM ${prefix}_rolling
    `
}

// Every daily query returns (date, total, failures) for one region.
export const dailyQueries = {
    alerts: (region: Region): string => heredoc`
        SELECT
            toDate(timestamp) AS date,
            count() AS total,
            countIf(properties.outcome = 'failure' OR properties.alert_state = 'Errored') AS failures
        FROM events
        WHERE event = 'slo_operation_completed'
            AND properties.operation = 'alert_check'
            AND properties.alert_type = 'insight'
            AND upper(properties.region) = upper('${region.toUpperCase()}')
            AND properties.skip_reason IS NULL
            AND timestamp >= now() - INTERVAL 30 DAY
        GROUP BY date
    `,

    // Tolerances on the gap between consecutive checks: hourly 60 min, daily 1440 min, weekly
    // 10080 min, monthly 44640 min. Looks back 45 days so monthly alerts have a previous check in
    // the 30-day window.
    alerts_timeliness: (region: Region): string => heredoc`
        WITH alert_checks AS (
            SELECT
                properties.resource_id AS alert_id,
                properties.calculation_interval AS calculation_interval,
                timestamp,
                lagInFrame(timestamp) OVER (
                    PARTITION BY properties.resource_id, properties.calculation_interval
                    ORDER BY timestamp ASC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                ) AS prev_check
            FROM events
            WHERE event = 'slo_operation_completed'
                AND properties.operation = 'alert_check'
                AND properties.alert_type = 'insight'
                AND upper(properties.region) = upper('${region.toUpperCase()}')
                AND properties.skip_reason IS NULL
                AND properties.calculation_interval IN ('hourly', 'daily', 'weekly', 'monthly')
                AND timestamp >= now() - INTERVAL 45 DAY
        )
        SELECT
            toDate(timestamp) AS date,
            count()           AS total,
            countIf(
                (calculation_interval = 'hourly'  AND dateDiff('minute', prev_check, timestamp) > 60)    OR
                (calculation_interval = 'daily'   AND dateDiff('minute', prev_check, timestamp) > 1440)  OR
                (calculation_interval = 'weekly'  AND dateDiff('minute', prev_check, timestamp) > 10080) OR
                (calculation_interval = 'monthly' AND dateDiff('minute', prev_check, timestamp) > 44640)
            ) AS failures
        FROM alert_checks
        WHERE prev_check != toDateTime(0)
            AND toDate(timestamp) >= toDate(now()) - 30
        GROUP BY date
    `,

    // A 10-minute grace period leaves out exports still in progress.
    exports: (region: Region): string => heredoc`
        SELECT
            toDate(created_at) AS date,
            count() AS total,
            countIf(export_context IS NULL AND content_location IS NULL) AS failures
        FROM ${tables[region].exports}
        WHERE created_at >= now() - INTERVAL 30 DAY
            AND created_at < now() - INTERVAL 10 MINUTE
        GROUP BY date
    `,

    subscriptions: (region: Region): string => heredoc`
        -- Attribute outcomes to the day the delivery started. A started workflow
        -- without a successful completion is a failed SLO operation, including a
        -- workflow that crashes before the interceptor can emit completion.
        WITH starts AS (
            SELECT
                toDate(min(timestamp)) AS date,
                properties.correlation_id AS correlation_id
            FROM events
            WHERE event = 'slo_operation_started'
                AND properties.operation = 'subscription_delivery'
                AND upper(properties.region) = upper('${region.toUpperCase()}')
                AND timestamp >= now() - INTERVAL 30 DAY
            GROUP BY correlation_id
        ), completed AS (
            SELECT
                properties.correlation_id AS correlation_id,
                max(properties.outcome = 'success') AS succeeded
            FROM events
            WHERE event = 'slo_operation_completed'
                AND properties.operation = 'subscription_delivery'
                AND upper(properties.region) = upper('${region.toUpperCase()}')
                AND timestamp >= now() - INTERVAL 30 DAY
            GROUP BY correlation_id
        )
        SELECT
            starts.date,
            count() AS total,
            countIf(coalesce(completed.succeeded, false) = false) AS failures
        FROM starts
        LEFT JOIN completed USING (correlation_id)
        GROUP BY starts.date
    `,

    // Cohorts not calculated within a day count as failures.
    cohorts: (region: Region): string => heredoc`
        SELECT
            cc.date,
            count() AS total,
            count() - countIf(dc.successes > 0) AS failures
        FROM (
            SELECT d.date, c.cohort_id
            FROM (SELECT toDate(now()) - number AS date FROM numbers(37)) d
            CROSS JOIN (
                SELECT cohort_id, min(toDate(finished_at)) AS first_seen
                FROM ${tables[region].history}
                WHERE finished_at >= now() - INTERVAL 37 DAY
                GROUP BY cohort_id
            ) c
            WHERE c.first_seen <= d.date
        ) cc
        LEFT JOIN (
            SELECT
                toDate(finished_at) AS date,
                cohort_id,
                countIf(error_code IS NULL OR error_code = '') AS successes
            FROM ${tables[region].history}
            WHERE finished_at >= now() - INTERVAL 30 DAY
                AND finished_at IS NOT NULL
            GROUP BY date, cohort_id
        ) dc ON cc.date = dc.date AND cc.cohort_id = dc.cohort_id
        WHERE cc.date >= toDate(now()) - 30
        GROUP BY cc.date
    `,
}

export interface SloQuery {
    key: string
    name: string
    daily: string
}

// One chart of every SLO's 30-day success rate, from one CTE block per SLO.
export function successRateQuery(slos: readonly SloQuery[]): string {
    const ctes = slos.map((slo) => successCte(slo.key, slo.daily))
    const selects = slos.map((slo) => successSelect(slo.key, slo.name))
    return heredoc`
        WITH
            date_range AS (SELECT toDate(now()) - number AS date FROM numbers(30)),
            ${ctes.join(',\n        ')}
        SELECT date, slo, value FROM (
            ${selects.join('\n        UNION ALL\n        ')}
        )
        ORDER BY date ASC, slo ASC
        LIMIT 500
    `
}
