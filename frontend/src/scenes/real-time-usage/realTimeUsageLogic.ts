import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { ApiRequest } from 'lib/api'
import { AppMetricsTimeSeriesResponse } from 'lib/components/AppMetrics/appMetricsLogic'
import { type Dayjs, dayjs } from 'lib/dayjs'
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

const RANGE_STEPS: Record<UsageRange, { amount: number; unit: 'hour' | 'day' }> = {
    '1d': { amount: 24, unit: 'hour' },
    '7d': { amount: 7, unit: 'day' },
    '30d': { amount: 30, unit: 'day' },
}

const UNIT_MINUTES = { minute: 1, hour: 60, day: 24 * 60 } as const

const GRANULARITIES: Record<UsageGranularity, { bucket: string; amount: number; unit: keyof typeof UNIT_MINUTES }> = {
    '5m': { bucket: 'toStartOfFiveMinutes(recorded_at)', amount: 5, unit: 'minute' },
    hour: { bucket: "dateTrunc('hour', recorded_at)", amount: 1, unit: 'hour' },
    day: { bucket: "dateTrunc('day', recorded_at)", amount: 1, unit: 'day' },
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

// dayjs has no five-minute unit, so floor the minutes by hand to match toStartOfFiveMinutes.
function startOfBucket(time: Dayjs, granularity: UsageGranularity): Dayjs {
    if (granularity === '5m') {
        const minute = time.startOf('minute')
        return minute.subtract(minute.minute() % GRANULARITIES['5m'].amount, 'minute')
    }
    return time.startOf(granularity)
}

function bucketLabels(range: UsageRange, granularity: UsageGranularity): string[] {
    const { amount, unit } = GRANULARITIES[granularity]
    const rangeStep = RANGE_STEPS[range]
    const count = (rangeStep.amount * UNIT_MINUTES[rangeStep.unit]) / (amount * UNIT_MINUTES[unit]) + 1
    const start = startOfBucket(dayjs().subtract(rangeStep.amount, rangeStep.unit), granularity)

    return Array.from({ length: count }, (_, index) => start.add(index * amount, unit).format('YYYY-MM-DD HH:mm'))
}

function usageQuery(range: UsageRange, granularity: UsageGranularity, timeSeries: boolean): string {
    const interval = RANGE_INTERVALS[range]
    const bucket = GRANULARITIES[granularity].bucket
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
    const series = new Map<string, Map<string, number>>()

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
            const normalizedBucket = dayjs(String(bucket)).format('YYYY-MM-DD HH:mm')
            const values = series.get(String(seriesName)) ?? new Map<string, number>()
            values.set(normalizedBucket, (values.get(normalizedBucket) ?? 0) + Number(quantity))
            series.set(String(seriesName), values)
        }
    }

    const labels = bucketLabels(range, granularity)
    return {
        rows: Array.from(rows.values()).sort(
            (a, b) => b.quantity - a.quantity || a.producerId.localeCompare(b.producerId)
        ),
        timeSeries: {
            labels,
            series: Array.from(series.entries()).map(([name, values]) => ({
                name,
                values: labels.map((label) => values.get(label) ?? 0),
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
