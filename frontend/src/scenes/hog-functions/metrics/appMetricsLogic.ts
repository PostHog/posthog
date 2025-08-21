import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { HogQLQueryString, hogql } from '~/queries/utils'

import type { appMetricsLogicType } from './appMetricsLogicType'

// Type for interval units
type IntervalUnit = 'day' | 'hour' | 'minute' | 'second'

// Type for interval strings like "1 day", "2 hour", etc.
type IntervalString = `${number} ${IntervalUnit}` | IntervalUnit

export type AppMetricsCommonParams = {
    appSource?: string
    appSourceId?: string
    instanceId?: string
    metricName?: string | string[]
    metricKind?: string | string[]
    breakdownBy?: 'metric_name' | 'metric_kind' | 'app_source_id'
    interval?: IntervalString
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
    timestamp: string
    breakdown: string
    count: number[]
}[]

const loadAppMetricsTimeSeries = async (
    request: AppMetricsTimeSeriesRequest
): Promise<AppMetricsTimeSeriesResponse> => {
    // Parse interval - handle both "1 day" and "day" formats
    const interval = request.interval || '1 day'

    let query = hogql`
        SELECT
            toStartOfInterval(timestamp, INTERVAL ${hogql.raw(interval)}) as timestamp,
            ${hogql.raw(request.breakdownBy!)} as breakdown,
            sum(count) as count
        FROM app_metrics
        WHERE app_source = ${request.appSource}
        AND timestamp > toStartOfInterval({filters.dateRange.from}, INTERVAL ${hogql.raw(interval)})
        AND timestamp < toEndOfInterval({filters.dateRange.to}, INTERVAL ${hogql.raw(interval)})
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
        hogql`\nGROUP BY timestamp, ${hogql.raw(request.breakdownBy!)} ORDER BY timestamp ASC`) as HogQLQueryString

    // oxlint-disable-next-line no-console
    console.log('Performing', query)

    const response = await api.queryHogQL(query, {
        refresh: 'force_blocking',
        filtersOverride: {
            date_from: request.before ?? '-7d',
            date_to: request.after,
        },
    })

    // oxlint-disable-next-line no-console
    console.log('Response', response.results)

    return response.results.map((result) => ({
        timestamp: result[0],
        breakdown: result[1],
        count: result[2],
    }))
}

// IDEA - have a generic helper logic that can be used anywhere for rendering metrics
export const appMetricsLogic = kea<appMetricsLogicType>([
    props({} as unknown as AppMetricsLogicProps),
    key(({ logicKey }: AppMetricsLogicProps) => logicKey),
    path((id) => ['scenes', 'hog-functions', 'metrics', 'appMetricsLogic', id]),
    actions({
        // set: (filters: Partial<AppMetricsFilters>) => ({ filters }),
    }),
    loaders(({ props }) => ({
        appMetricsTrends: [
            null as AppMetricsTimeSeriesResponse | null,
            {
                loadAppMetricsTrends: async () => {
                    const params: AppMetricsTimeSeriesRequest = {
                        ...props.forceParams,
                    }
                    return await loadAppMetricsTimeSeries(params)
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
