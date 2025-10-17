import { actions, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { dateStringToDayJs, objectsEqual } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import { HogQLQueryString, hogql } from '~/queries/utils'

import type { appMetricsLogicType } from './appMetricsLogicType'

const DEFAULT_INTERVAL = 'day'

export type AppMetricsCommonParams = {
    appSource?: string
    appSourceId?: string
    instanceId?: string
    metricName?: string | string[]
    metricKind?: string | string[]
    breakdownBy?: 'metric_name' | 'metric_kind' | 'app_source_id'
    interval?: 'day' | 'hour' | 'minute'
    dateFrom?: string
    dateTo?: string
}

export type AppMetricsLogicProps = {
    logicKey: string
    forceParams?: Partial<AppMetricsCommonParams>
    defaultParams?: Partial<AppMetricsCommonParams>
    loadOnChanges?: boolean
}

export type AppMetricsTimeSeriesRequest = AppMetricsCommonParams

export type AppMetricsTimeSeriesResponse = {
    labels: string[]
    series: {
        name: string
        values: number[]
    }[]
}

export type AppMetricsTotalsRequest = Omit<AppMetricsCommonParams, 'interval' | 'breakdownBy'> & {
    breakdownBy: ('metric_name' | 'metric_kind' | 'app_source_id' | 'instance_id')[]
}

export type AppMetricsTotalsResponse = Record<
    string,
    {
        total: number
        breakdowns: string[]
    }
>

export const loadAppMetricsTotals = async (
    request: AppMetricsTotalsRequest,
    timezone: string
): Promise<AppMetricsTotalsResponse> => {
    const breakdownBy = request.breakdownBy || ['metric_name']

    let query = hogql`
        SELECT
            sum(count) AS total,
            ${hogql.raw(breakdownBy.join(', '))}
        FROM app_metrics
        WHERE app_source = ${request.appSource}
    `

    if (request.appSourceId) {
        query = (query + hogql`\nAND app_source_id = ${request.appSourceId}`) as HogQLQueryString
    }
    if (typeof request.instanceId === 'string') {
        query = (query + hogql`\nAND instance_id = ${request.instanceId}`) as HogQLQueryString
    }
    if (request.metricName) {
        const metricNames = Array.isArray(request.metricName) ? request.metricName : [request.metricName]
        query = (query + hogql`\nAND metric_name IN ${metricNames}`) as HogQLQueryString
    }
    if (request.metricKind) {
        const metricKinds = Array.isArray(request.metricKind) ? request.metricKind : [request.metricKind]
        query = (query + hogql`\nAND metric_kind IN ${metricKinds}`) as HogQLQueryString
    }

    query = (query +
        hogql`
            AND toTimeZone(timestamp, ${timezone}) >= toDateTime(${request.dateFrom}, ${timezone})
            AND toTimeZone(timestamp, ${timezone}) < toDateTime(${request.dateTo}, ${timezone})
            GROUP BY ${hogql.raw(breakdownBy.join(', '))}
        `) as HogQLQueryString

    const response = await api.queryHogQL(query, {
        refresh: 'async',
    })

    const res: AppMetricsTotalsResponse = {}

    response.results?.forEach((result) => {
        const total = result[0] as number
        const groups = result.slice(1)

        // Create a key that combines instanceId and metricName
        const key = groups.join('_')
        res[key] = { total, breakdowns: groups }
    })

    return res
}

const loadAppMetricsTimeSeries = async (
    request: AppMetricsTimeSeriesRequest,
    timezone: string
): Promise<AppMetricsTimeSeriesResponse> => {
    const interval = request.interval || DEFAULT_INTERVAL

    let query = hogql`
        WITH
            ${timezone} AS tz,
            ${interval} AS g,

            -- Interpret the input bounds in the user's TZ
            toDateTime(${request.dateFrom}, tz) AS from_local,
            toDateTime(${request.dateTo},   tz) AS to_local,

            -- Snap to buckets in that TZ
            dateTrunc(g, from_local, tz) AS start_bucket,
            dateTrunc(g, to_local,   tz) AS end_bucket,

            -- Number of buckets (inclusive), DST-safe
            multiIf(
                g = 'minute', dateDiff('minute', start_bucket, end_bucket) + 1,
                g = 'hour',   dateDiff('hour',   start_bucket, end_bucket) + 1,
                g = 'day',    dateDiff('day',    start_bucket, end_bucket) + 1,
                g = 'week',   dateDiff('week',   start_bucket, end_bucket) + 1,
                0
            ) AS steps,

            -- Calendar of bucket starts, stepped by units (not seconds), DST-safe
            arrayMap(n ->
                multiIf(
                    g = 'minute', addMinutes(start_bucket, n),
                    g = 'hour',   addHours(start_bucket, n),
                    g = 'day',    addDays(start_bucket, n),
                    g = 'week',   addWeeks(start_bucket, n),
                    start_bucket
                ),
                range(0, steps)
            ) AS calendar

        SELECT
            calendar AS date,
            breakdown,
            arrayMap(d -> if(indexOf(buckets, d) = 0, 0, counts[indexOf(buckets, d)]), calendar) AS total
        FROM
        (
            SELECT
                breakdown,
                groupArray(bucket) AS buckets,
                groupArray(cnt)    AS counts
            FROM
            (
                SELECT
                    ${hogql.raw(request.breakdownBy!)} AS breakdown,
                    -- Convert data to user's TZ before truncating
                    dateTrunc(g, toTimeZone(timestamp, tz), tz) AS bucket,
                    sum(count) AS cnt
                FROM app_metrics
                WHERE app_source = ${request.appSource}
    `

    if (request.appSourceId) {
        query = (query + hogql`\nAND app_source_id = ${request.appSourceId}`) as HogQLQueryString
    }
    if (typeof request.instanceId === 'string') {
        query = (query + hogql`\nAND instance_id = ${request.instanceId}`) as HogQLQueryString
    }
    if (request.metricName) {
        const metricNames = Array.isArray(request.metricName) ? request.metricName : [request.metricName]
        query = (query + hogql`\nAND metric_name IN ${metricNames}`) as HogQLQueryString
    }
    if (request.metricKind) {
        const metricKinds = Array.isArray(request.metricKind) ? request.metricKind : [request.metricKind]
        query = (query + hogql`\nAND metric_kind IN ${metricKinds}`) as HogQLQueryString
    }

    query = (query +
        hogql`
                AND toTimeZone(timestamp, tz) >= start_bucket
                AND toTimeZone(timestamp, tz) < multiIf(
                        g = 'minute', addMinutes(end_bucket, 1),
                        g = 'hour',   addHours(end_bucket,   1),
                        g = 'day',    addDays(end_bucket,    1),
                        g = 'week',   addWeeks(end_bucket,   1),
                        end_bucket
                )
                GROUP BY breakdown, bucket
                ORDER BY breakdown, bucket
            )
            GROUP BY breakdown
        )
        ORDER BY breakdown
        `) as HogQLQueryString

    const response = await api.queryHogQL(query, {
        refresh: 'async',
    })

    const labels = response.results?.[0]?.[0].map((label: string) => {
        switch (interval) {
            case 'day':
                return dayjs(label).tz(timezone).format('YYYY-MM-DD')
            case 'hour':
                return dayjs(label).tz(timezone).format('YYYY-MM-DD HH:mm')
            case 'minute':
                return dayjs(label).tz(timezone).format('YYYY-MM-DD HH:mm')
        }
    })

    return {
        labels: labels || [],
        series:
            response.results?.map((result) => ({
                name: result[1],
                values: result[2],
            })) || [],
    }
}

const convertDateFieldToDayJs = (date: string, timezone: string): Dayjs => {
    return dateStringToDayJs(date, timezone) ?? dayjs().tz(timezone)
}

// IDEA - have a generic helper logic that can be used anywhere for rendering metrics
export const appMetricsLogic = kea<appMetricsLogicType>([
    props({} as unknown as AppMetricsLogicProps),
    key(({ logicKey }: AppMetricsLogicProps) => logicKey),
    path((id) => ['scenes', 'hog-functions', 'metrics', 'appMetricsLogic', id]),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    actions({
        setParams: (params: Partial<AppMetricsCommonParams>) => ({ params }),
        loadAppMetricsTrends: true,
        loadAppMetricsTrendsPreviousPeriod: true,
    }),
    reducers(({ props }) => ({
        params: [
            {
                interval: DEFAULT_INTERVAL,
                dateFrom: '-7d',
                ...props.defaultParams,
                ...props.forceParams,
            } as Partial<AppMetricsCommonParams>,
            {
                setParams: (state, { params }) => ({ ...state, ...params }),
            },
        ],
    })),
    lazyLoaders(({ values }) => ({
        appMetricsTrends: [
            null as AppMetricsTimeSeriesResponse | null,
            {
                loadAppMetricsTrends: async (_, breakpoint) => {
                    await breakpoint(10)
                    const dateRange = values.getDateRangeAbsolute()
                    const params: AppMetricsTimeSeriesRequest = {
                        ...values.params,
                        dateFrom: dateRange.dateFrom.toISOString(),
                        dateTo: dateRange.dateTo.toISOString(),
                    }

                    const result = await loadAppMetricsTimeSeries(params, values.currentTeam?.timezone ?? 'UTC')
                    await breakpoint(10)

                    return result
                },
            },
        ],
        appMetricsTrendsPreviousPeriod: [
            null as AppMetricsTimeSeriesResponse | null,
            {
                loadAppMetricsTrendsPreviousPeriod: async (_, breakpoint) => {
                    await breakpoint(10)
                    const dateRange = values.getDateRangeAbsolute()
                    const params: AppMetricsTimeSeriesRequest = {
                        ...values.params,
                        dateFrom: dateRange.dateFrom.subtract(dateRange.diffMs).toISOString(),
                        dateTo: dateRange.dateTo.subtract(dateRange.diffMs).toISOString(),
                    }

                    const result = await loadAppMetricsTimeSeries(params, values.currentTeam?.timezone ?? 'UTC')
                    await breakpoint(10)

                    return result
                },
            },
        ],
    })),
    selectors(() => ({
        getSingleTrendSeries: [
            (s) => [s.appMetricsTrends, s.appMetricsTrendsPreviousPeriod],
            (appMetricsTrends, appMetricsTrendsPreviousPeriod) =>
                (name: string, previousPeriod: boolean = false): AppMetricsTimeSeriesResponse | null => {
                    const targetTrend = previousPeriod ? appMetricsTrendsPreviousPeriod : appMetricsTrends
                    if (!targetTrend) {
                        return null
                    }
                    const series = targetTrend.series.find((s) => s.name === name) || {
                        name,
                        values: Array.from({ length: targetTrend.labels.length }, () => 0),
                    }

                    return {
                        labels: targetTrend.labels,
                        series: [series],
                    }
                },
        ],

        getDateRangeAbsolute: [
            (s) => [s.params, s.currentTeam],
            (params, currentTeam) => (): { dateFrom: Dayjs; dateTo: Dayjs; diffMs: number } => {
                const dateFrom = convertDateFieldToDayJs(params.dateFrom ?? '-7d', currentTeam?.timezone ?? 'UTC')
                const dateTo = params.dateTo
                    ? convertDateFieldToDayJs(params.dateTo, currentTeam?.timezone ?? 'UTC')
                    : dayjs()
                          .tz(currentTeam?.timezone ?? 'UTC')
                          .endOf(params.interval ?? DEFAULT_INTERVAL)

                const diffMs = dateTo.diff(dateFrom)

                return { dateFrom, dateTo, diffMs }
            },
        ],

        availableIntervals: [
            (s) => [s.getDateRangeAbsolute],
            (getDateRangeAbsolute): AppMetricsCommonParams['interval'][] => {
                const diffMs = getDateRangeAbsolute().diffMs

                // If the diff is less than 2 days (ish), we can show the minute interval but not day
                if (diffMs <= 1000 * 60 * 60 * 49) {
                    return ['hour']
                }

                // If the diff is less than 8 days, we can show the hour interval but not minute
                if (diffMs <= 1000 * 60 * 60 * 24 * 8) {
                    return ['day', 'hour']
                }

                // If the diff is greater than 8 days, we limit to day interval
                return ['day']
            },
        ],
    })),

    subscriptions(({ values, actions }) => ({
        availableIntervals: (availableIntervals) => {
            if (!availableIntervals.includes(values.params.interval)) {
                actions.setParams({ interval: availableIntervals[0] })
            }
        },
    })),

    propsChanged(({ actions, props }, oldProps) => {
        if (props.forceParams && !objectsEqual(props.forceParams, oldProps.forceParams)) {
            actions.setParams({ ...props.forceParams })
        }
    }),

    listeners(({ actions, values, props }) => ({
        setParams: async (_, breakpoint) => {
            await breakpoint(100)

            if (props.loadOnChanges ?? true) {
                if (values.appMetricsTrends !== null) {
                    actions.loadAppMetricsTrends()
                    actions.loadAppMetricsTrendsPreviousPeriod()
                }
            }
        },
    })),
])
