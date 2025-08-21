import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { HogQLQueryString, hogql } from '~/queries/utils'

import type { appMetricsLogicType } from './appMetricsLogicType'

export type AppMetricsCommonParams = {
    appSource?: string
    appSourceId?: string
    instanceId?: string
    metricName?: string | string[]
    metricKind?: string | string[]
    breakdownBy?: 'metric_name' | 'metric_kind' | 'app_source_id'
    interval?: 'day' | 'hour' | 'minute'
    before?: string
    after?: string
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

const loadAppMetricsTimeSeries = async (
    request: AppMetricsTimeSeriesRequest,
    timezone: string
): Promise<AppMetricsTimeSeriesResponse> => {
    const interval = request.interval || 'day'
    const dateFrom = dayjs().tz(timezone).subtract(7, 'day').toISOString()
    const dateTo = dayjs().tz(timezone).toISOString()

    let query = hogql`
        WITH
            ${interval} AS g,
            /* snap bounds to the granularity */
            dateTrunc(g, toDateTime(${dateFrom})) AS start_bucket,
            dateTrunc(g, toDateTime(${dateTo}))   AS end_bucket,

            /* step in seconds for the chosen granularity */
            multiIf(
                g = 'minute', 60,
                g = 'hour',   3600,
                g = 'day',    86400,
                g = 'week',   7*86400,
                1
            ) AS step_s,

            /* number of points, inclusive of end_bucket */
            (intDiv(toInt(end_bucket - start_bucket), step_s) + 1) AS steps,

            /* calendar of bucket starts (DateTime) */
            arrayMap(n -> start_bucket + (n * step_s), range(0, steps)) AS calendar

        SELECT
            calendar AS date,
            breakdown,
            /* for each calendar bucket, take matching count or 0 */
            arrayMap(d -> if(indexOf(days, d) = 0, 0, counts[indexOf(days, d)]), calendar) AS total
        FROM
        (
            SELECT
                breakdown,
                groupArray(bucket) AS days,
                groupArray(cnt)    AS counts
            FROM
            (
                SELECT
                    ${hogql.raw(request.breakdownBy!)} AS breakdown,
                    dateTrunc(g, timestamp) AS bucket,
                    sum(count) AS cnt
                FROM app_metrics
                WHERE app_source = ${request.appSource}
    `

    if (request.appSourceId) {
        query = (query + hogql`\nAND app_source_id = ${request.appSourceId}`) as HogQLQueryString
    }
    if (request.instanceId) {
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
                AND timestamp >= start_bucket
                AND timestamp < (end_bucket + step_s)
                GROUP BY breakdown, bucket
                ORDER BY breakdown, bucket
            )
            GROUP BY breakdown
        )
        ORDER BY breakdown
        `) as HogQLQueryString

    const response = await api.queryHogQL(query, {
        refresh: 'force_blocking',
        filtersOverride: {
            date_from: request.before ?? '-7d',
            date_to: request.after,
        },
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

// IDEA - have a generic helper logic that can be used anywhere for rendering metrics
export const appMetricsLogic = kea<appMetricsLogicType>([
    props({} as unknown as AppMetricsLogicProps),
    key(({ logicKey }: AppMetricsLogicProps) => logicKey),
    path((id) => ['scenes', 'hog-functions', 'metrics', 'appMetricsLogic', id]),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    actions({
        // set: (filters: Partial<AppMetricsFilters>) => ({ filters }),
    }),
    loaders(({ props, values }) => ({
        appMetricsTrends: [
            null as AppMetricsTimeSeriesResponse | null,
            {
                loadAppMetricsTrends: async () => {
                    const params: AppMetricsTimeSeriesRequest = {
                        ...props.forceParams,
                    }
                    return await loadAppMetricsTimeSeries(params, values.currentTeam?.timezone ?? 'UTC')
                },
            },
        ],
    })),
    reducers({
        // filters: [
        //     {
        //         name: '',
        //         date_from: '-7d',
        //         date_to: undefined,
        //         breakdown_by: 'name',
        //         interval: 'day',
        //     },
        //     {
        //         setFilters: (state, { filters }) => ({ ...state, ...filters }),
        //     },
        // ],
    }),
    selectors(() => ({
        getSingleTrendSeries: [
            (s) => [s.appMetricsTrends],
            (appMetricsTrends) =>
                (name: string): AppMetricsTimeSeriesResponse | null => {
                    if (!appMetricsTrends) {
                        return null
                    }
                    const series = appMetricsTrends.series.find((s) => s.name === name)
                    return {
                        labels: appMetricsTrends.labels,
                        series: series ? [series] : [],
                    }
                },
        ],
    })),

    listeners(({ actions, values, props }) => ({
        setFilters: async (_, breakpoint) => {
            await breakpoint(100)
            if (props.loadOnChanges) {
                if (values.appMetricsTrends !== null) {
                    actions.loadAppMetricsTrends()
                }
            }
        },
    })),
])
