import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { ApiRequest } from 'lib/api'
import { AppMetricsTimeSeriesResponse } from 'lib/components/AppMetrics/appMetricsLogic'
import { dayjs } from 'lib/dayjs'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { OrganizationType } from '~/types'

export type UsageGranularity = '5m' | 'hour' | 'day'
export type UsageRange = '1d' | '7d' | '30d'

export type RealTimeUsageRow = { producerId: string; usageKey: string; unit: string; quantity: number }

type RealTimeUsageData = {
    rows: RealTimeUsageRow[]
    timeSeries: AppMetricsTimeSeriesResponse
}

const RANGE_INTERVALS: Record<UsageRange, string> = {
    '1d': '24 HOUR',
    '7d': '7 DAY',
    '30d': '30 DAY',
}

const RANGE_SECONDS: Record<UsageRange, number> = {
    '1d': 24 * 60 * 60,
    '7d': 7 * 24 * 60 * 60,
    '30d': 30 * 24 * 60 * 60,
}

// Buckets are cut by integer arithmetic on the Unix timestamp rather than by dateTrunc, so a bucket
// is the same absolute instant for every project and for the browser. dateTrunc cuts on the team's
// timezone, and the chart merges several projects into one axis, so its boundaries disagreed both
// between projects and with the labels built here.
const GRANULARITY_SECONDS: Record<UsageGranularity, number> = {
    '5m': 5 * 60,
    hour: 60 * 60,
    day: 24 * 60 * 60,
}

// 289 points over 24 hours stays readable. The same buckets over 7 days would plot 2,017.
export function isGranularityAvailable(granularity: UsageGranularity, range: UsageRange): boolean {
    return granularity !== '5m' || range === '1d'
}

export type UsageFilters = { range: UsageRange; granularity: UsageGranularity }

// A shared or reloaded URL can carry anything, so fall back rather than query on a bad value.
export function filtersFromParams(searchParams: Record<string, any>): UsageFilters {
    const range: UsageRange =
        searchParams.range === '7d' || searchParams.range === '30d' || searchParams.range === '1d'
            ? searchParams.range
            : '1d'
    const granularity: UsageGranularity =
        searchParams.granularity === '5m' || searchParams.granularity === 'day' || searchParams.granularity === 'hour'
            ? searchParams.granularity
            : 'hour'
    return { range, granularity }
}

// Bucket starts as Unix seconds, matching what the query returns.
function bucketStarts(range: UsageRange, granularity: UsageGranularity): number[] {
    const step = GRANULARITY_SECONDS[granularity]
    const count = RANGE_SECONDS[range] / step + 1
    const end = Math.floor(dayjs().unix() / step) * step

    return Array.from({ length: count }, (_, index) => end - (count - 1 - index) * step)
}

function usageQuery(range: UsageRange, granularity: UsageGranularity, timeSeries: boolean): string {
    const interval = RANGE_INTERVALS[range]
    const step = GRANULARITY_SECONDS[granularity]
    const bucket = `intDiv(toUnixTimestamp(recorded_at), ${step}) * ${step}`
    // Grouped by the table's sorting key so un-merged duplicates of one record collapse instead
    // of summing. HogQL rejects FINAL, and timestamp is monotonic per resend, so argMax on it
    // picks the same row a merge would keep.
    const canonicalRecords = `SELECT producer_id, usage_key, unit, record_id, argMax(quantity, timestamp) AS quantity, max(timestamp) AS recorded_at FROM posthog.billing_usage_records WHERE timestamp >= now() - INTERVAL ${interval} GROUP BY toDate(timestamp), producer_id, usage_key, unit, record_id`

    return timeSeries
        ? `SELECT ${bucket} AS bucket, concat(producer_id, ': ', usage_key, ' (', unit, ')') AS series, sum(quantity) AS quantity FROM (${canonicalRecords}) GROUP BY bucket, series ORDER BY bucket, series`
        : `SELECT producer_id, usage_key, unit, sum(quantity) AS quantity FROM (${canonicalRecords}) GROUP BY producer_id, usage_key, unit ORDER BY quantity DESC, producer_id, usage_key`
}

async function queryUsage(teamId: number, query: string): Promise<HogQLQueryResponse> {
    return await new ApiRequest().query(teamId, NodeKind.HogQLQuery).create({
        data: {
            query: {
                kind: NodeKind.HogQLQuery,
                tags: { scene: 'RealTimeUsage' },
                query,
            },
            refresh: 'force_blocking',
        },
    })
}

function parseUsageData(
    responses: { rows: HogQLQueryResponse; timeSeries: HogQLQueryResponse }[],
    range: UsageRange,
    granularity: UsageGranularity
): RealTimeUsageData {
    const rows = new Map<string, RealTimeUsageRow>()
    const series = new Map<string, Map<number, number>>()

    for (const response of responses) {
        for (const [producerId, usageKey, unit, quantity] of response.rows.results ?? []) {
            const key = `${producerId}:${usageKey}:${unit}`
            const current = rows.get(key)
            rows.set(key, {
                producerId: String(producerId),
                usageKey: String(usageKey),
                unit: String(unit),
                quantity: (current?.quantity ?? 0) + Number(quantity),
            })
        }

        for (const [bucket, seriesName, quantity] of response.timeSeries.results ?? []) {
            const bucketStart = Number(bucket)
            const values = series.get(String(seriesName)) ?? new Map<number, number>()
            values.set(bucketStart, (values.get(bucketStart) ?? 0) + Number(quantity))
            series.set(String(seriesName), values)
        }
    }

    const starts = bucketStarts(range, granularity)
    return {
        rows: Array.from(rows.values()).sort(
            (a, b) => b.quantity - a.quantity || a.producerId.localeCompare(b.producerId)
        ),
        timeSeries: {
            // Buckets are UTC-aligned, so label them in UTC rather than in the reader's timezone.
            labels: starts.map((start) => dayjs.unix(start).utc().format('YYYY-MM-DD HH:mm')),
            series: Array.from(series.entries()).map(([name, values]) => ({
                name,
                values: starts.map((start) => values.get(start) ?? 0),
            })),
        },
    }
}

export interface realTimeUsageLogicValues {
    currentOrganization: OrganizationType | null
    usageData: RealTimeUsageData | null
    usageDataError: string | null
    usageDataLoading: boolean
    usageGranularity: UsageGranularity
    usageRange: UsageRange
}
export interface realTimeUsageLogicActions {
    loadUsageData: () => { value: true }
    loadUsageDataSuccess: (
        usageData: RealTimeUsageData,
        payload?: { value: true }
    ) => {
        usageData: RealTimeUsageData
        payload?: { value: true }
    }
    loadUsageDataFailure: (error: string, errorObject?: Error) => { error: string; errorObject?: Error }
    setUsageFilters: (filters: UsageFilters) => { filters: UsageFilters }
}
export type realTimeUsageLogicType = MakeLogicType<realTimeUsageLogicValues, realTimeUsageLogicActions>

export const realTimeUsageLogic = kea<realTimeUsageLogicType>([
    path(['scenes', 'real-time-usage', 'realTimeUsageLogic']),
    connect(() => ({ values: [organizationLogic, ['currentOrganization']] })),
    actions({
        // Normalized here so every caller, including a hand-edited URL, lands on a valid pair.
        setUsageFilters: (filters: UsageFilters) => ({
            filters: {
                ...filters,
                granularity: isGranularityAvailable(filters.granularity, filters.range) ? filters.granularity : 'hour',
            },
        }),
    }),
    loaders(({ values }) => ({
        usageData: [
            null as RealTimeUsageData | null,
            {
                loadUsageData: async (): Promise<RealTimeUsageData> => {
                    const rowsQuery = usageQuery(values.usageRange, values.usageGranularity, false)
                    const timeSeriesQuery = usageQuery(values.usageRange, values.usageGranularity, true)
                    const responses = await Promise.all(
                        (values.currentOrganization?.teams ?? []).map(async (team) => ({
                            rows: await queryUsage(team.id, rowsQuery),
                            timeSeries: await queryUsage(team.id, timeSeriesQuery),
                        }))
                    )
                    return parseUsageData(responses, values.usageRange, values.usageGranularity)
                },
            },
        ],
    })),
    reducers({
        usageDataError: [
            null as string | null,
            {
                loadUsageData: () => null,
                loadUsageDataFailure: (_, { error }) => error,
            },
        ],
        usageGranularity: ['hour' as UsageGranularity, { setUsageFilters: (_, { filters }) => filters.granularity }],
        usageRange: ['1d' as UsageRange, { setUsageFilters: (_, { filters }) => filters.range }],
    }),
    listeners(({ actions }) => ({
        setUsageFilters: () => actions.loadUsageData(),
    })),
    actionToUrl(({ values }) => ({
        setUsageFilters: () => [
            router.values.location.pathname,
            { range: values.usageRange, granularity: values.usageGranularity },
            router.values.hashParams,
            { replace: true },
        ],
    })),
    urlToAction(({ actions, values }) => ({
        [urls.organizationBillingRealTimeUsage()]: (_, searchParams) => {
            const filters = filtersFromParams(searchParams)
            if (filters.range !== values.usageRange || filters.granularity !== values.usageGranularity) {
                actions.setUsageFilters(filters)
            }
        },
    })),
    // One action covers both filters, so the mount reads the URL and loads exactly once.
    afterMount(({ actions }) => actions.setUsageFilters(filtersFromParams(router.values.searchParams))),
])
