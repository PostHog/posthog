import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiRequest } from 'lib/api'
import { AppMetricsTimeSeriesResponse } from 'lib/components/AppMetrics/appMetricsLogic'
import { dayjs } from 'lib/dayjs'
import { organizationLogic } from 'scenes/organizationLogic'

import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { OrganizationType } from '~/types'

export type UsageGranularity = 'hour' | 'day'
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

function bucketLabels(range: UsageRange, granularity: UsageGranularity): string[] {
    const start = dayjs()
        .subtract(range === '1d' ? 24 : Number.parseInt(range, 10), range === '1d' ? 'hour' : 'day')
        .startOf(granularity)
    const count =
        granularity === 'hour'
            ? range === '1d'
                ? 25
                : Number.parseInt(range, 10) * 24 + 1
            : Number.parseInt(range, 10) + 1

    return Array.from({ length: count }, (_, index) => start.add(index, granularity).format('YYYY-MM-DD HH:mm'))
}

function usageQuery(range: UsageRange, granularity: UsageGranularity, timeSeries: boolean): string {
    const interval = RANGE_INTERVALS[range]
    const bucket = `dateTrunc('${granularity}', recorded_at)`
    const canonicalRecords = `SELECT producer_id, usage_key, unit, record_id, version, argMax(quantity, event_timestamp) AS quantity, max(event_timestamp) AS recorded_at FROM posthog.billing_usage_records WHERE event_timestamp >= now() - INTERVAL ${interval} GROUP BY producer_id, usage_key, unit, record_id, version`

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
    setUsageGranularity: (usageGranularity: UsageGranularity) => { usageGranularity: UsageGranularity }
    setUsageRange: (usageRange: UsageRange) => { usageRange: UsageRange }
}
export type realTimeUsageLogicType = MakeLogicType<realTimeUsageLogicValues, realTimeUsageLogicActions>

export const realTimeUsageLogic = kea<realTimeUsageLogicType>([
    path(['scenes', 'real-time-usage', 'realTimeUsageLogic']),
    connect(() => ({ values: [organizationLogic, ['currentOrganization']] })),
    actions({
        setUsageGranularity: (usageGranularity: UsageGranularity) => ({ usageGranularity }),
        setUsageRange: (usageRange: UsageRange) => ({ usageRange }),
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
        usageGranularity: [
            'hour' as UsageGranularity,
            { setUsageGranularity: (_, { usageGranularity }) => usageGranularity },
        ],
        usageRange: ['1d' as UsageRange, { setUsageRange: (_, { usageRange }) => usageRange }],
    }),
    listeners(({ actions }) => ({
        setUsageGranularity: () => actions.loadUsageData(),
        setUsageRange: () => actions.loadUsageData(),
    })),
    afterMount(({ actions }) => actions.loadUsageData()),
])
