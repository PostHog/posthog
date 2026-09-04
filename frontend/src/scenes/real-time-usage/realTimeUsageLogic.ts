import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { ApiRequest } from 'lib/api'
import { AppMetricsTimeSeriesResponse } from 'lib/components/AppMetrics/appMetricsLogic'
import { dayjs } from 'lib/dayjs'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { ConcurrencyController } from '~/lib/utils/concurrencyController'
import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { OrganizationType } from '~/types'

export type UsageGranularity = '5m' | 'hour' | 'day'
export type UsageRange = '1d' | '7d' | '30d'

export type RealTimeUsageRow = {
    projectName?: string
    producerId: string
    usageKey: string
    unit: string
    quantity: number
}

type RealTimeUsageData = {
    rows: RealTimeUsageRow[]
    timeSeries: AppMetricsTimeSeriesResponse
}

type ProjectUsageData = {
    project: { id: number; name: string }
    usage: HogQLQueryResponse
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

const PROJECT_QUERY_CONCURRENCY = 10

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

export type UsageFilters = {
    range: UsageRange
    granularity: UsageGranularity
    projectIds: number[]
    breakdownByProject: boolean
}

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
    // pinned: URL parameter names — bookmarks rely on them.
    const projectIds = String(searchParams.project_ids ?? '')
        .split(',')
        .filter(Boolean)
        .map(Number)
        .filter(Number.isInteger)
    const breakdownByProject =
        searchParams.breakdown_by_project === true || searchParams.breakdown_by_project === 'true'
    return { range, granularity, projectIds, breakdownByProject }
}

// Bucket starts as Unix seconds, matching what the query returns.
function bucketStarts(range: UsageRange, granularity: UsageGranularity): number[] {
    const step = GRANULARITY_SECONDS[granularity]
    const count = RANGE_SECONDS[range] / step + 1
    const end = Math.floor(dayjs().unix() / step) * step

    return Array.from({ length: count }, (_, index) => end - (count - 1 - index) * step)
}

// Collapsing an un-merged resend needs a group by record_id, which is unique per row, so the
// aggregation holds one state per row and exceeds ClickHouse's per-query memory limit. This page
// reports usage as it arrives rather than the billed number, so a plain sum is close enough.
// One query serves both the chart and the table, because the table is this result summed over its
// buckets.
function usageQuery(range: UsageRange, granularity: UsageGranularity): string {
    const interval = RANGE_INTERVALS[range]
    const step = GRANULARITY_SECONDS[granularity]

    return `SELECT intDiv(toUnixTimestamp(timestamp), ${step}) * ${step} AS bucket, producer_id, usage_key, unit, sum(quantity) AS quantity FROM posthog.billing_usage_records WHERE timestamp >= now() - INTERVAL ${interval} GROUP BY bucket, producer_id, usage_key, unit`
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

export function parseUsageData(
    responses: ProjectUsageData[],
    range: UsageRange,
    granularity: UsageGranularity,
    breakdownByProject: boolean
): RealTimeUsageData {
    const rows = new Map<string, RealTimeUsageRow>()
    const series = new Map<string, Map<number, number>>()

    for (const response of responses) {
        for (const [bucket, producerId, usageKey, unit, quantity] of response.usage.results ?? []) {
            const meter = `${producerId}: ${usageKey} (${unit})`
            const amount = Number(quantity)

            const rowKey = `${breakdownByProject ? `${response.project.id}:` : ''}${producerId}:${usageKey}:${unit}`
            const current = rows.get(rowKey)
            rows.set(rowKey, {
                projectName: breakdownByProject ? response.project.name : undefined,
                producerId: String(producerId),
                usageKey: String(usageKey),
                unit: String(unit),
                quantity: (current?.quantity ?? 0) + amount,
            })

            const seriesKey = breakdownByProject ? `${response.project.id}:${response.project.name}: ${meter}` : meter
            const values = series.get(seriesKey) ?? new Map<number, number>()
            const bucketStart = Number(bucket)
            values.set(bucketStart, (values.get(bucketStart) ?? 0) + amount)
            series.set(seriesKey, values)
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
            series: Array.from(series.entries()).map(([key, values]) => ({
                name: breakdownByProject ? key.replace(/^\d+:/, '') : key,
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
    selectedProjectIds: number[]
    breakdownByProject: boolean
    projectOptions: { key: string; label: string }[]
    hasMultipleProjects: boolean
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
    actions(({ values }) => ({
        // Normalized here so every caller, including a hand-edited URL, lands on a valid pair.
        setUsageFilters: (filters: UsageFilters) => {
            const teams = values.currentOrganization?.teams

            return {
                filters: {
                    ...filters,
                    granularity: isGranularityAvailable(filters.granularity, filters.range)
                        ? filters.granularity
                        : 'hour',
                    projectIds: teams
                        ? filters.projectIds.filter((projectId) => teams.some((team) => team.id === projectId))
                        : filters.projectIds,
                },
            }
        },
    })),
    loaders(({ values }) => ({
        usageData: [
            null as RealTimeUsageData | null,
            {
                loadUsageData: async (): Promise<RealTimeUsageData> => {
                    const query = usageQuery(values.usageRange, values.usageGranularity)
                    const teams = values.currentOrganization?.teams ?? []
                    const selectedTeams = values.selectedProjectIds.length
                        ? teams.filter((team) => values.selectedProjectIds.includes(team.id))
                        : teams
                    // Only allowlisted organizations resolve billing_usage_records, and the allowlist is
                    // server-side, so a project that cannot read it is skipped rather than failing
                    // the whole organization's chart.
                    const projectQueryConcurrency = new ConcurrencyController(PROJECT_QUERY_CONCURRENCY)
                    const settled = await Promise.allSettled(
                        selectedTeams.map((team) =>
                            projectQueryConcurrency.run({
                                fn: async () => ({
                                    project: { id: team.id, name: team.name },
                                    usage: await queryUsage(team.id, query),
                                }),
                            })
                        )
                    )
                    const responses = settled
                        .filter((result) => result.status === 'fulfilled')
                        .map((result) => result.value)
                    if (!responses.length && selectedTeams.length) {
                        throw settled[0].status === 'rejected' ? settled[0].reason : new Error('No usage data')
                    }
                    return parseUsageData(
                        responses,
                        values.usageRange,
                        values.usageGranularity,
                        values.breakdownByProject
                    )
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
        selectedProjectIds: [[], { setUsageFilters: (_, { filters }) => filters.projectIds }],
        breakdownByProject: [false, { setUsageFilters: (_, { filters }) => filters.breakdownByProject }],
    }),
    selectors({
        projectOptions: [
            (s) => [s.currentOrganization],
            (currentOrganization: OrganizationType | null): { key: string; label: string }[] =>
                [...(currentOrganization?.teams ?? [])]
                    .sort((a, b) => a.name.localeCompare(b.name))
                    .map((team) => ({ key: String(team.id), label: team.name })),
        ],
        hasMultipleProjects: [(s) => [s.projectOptions], (projectOptions): boolean => projectOptions.length > 1],
    }),
    listeners(({ actions }) => ({
        setUsageFilters: () => actions.loadUsageData(),
    })),
    actionToUrl(({ values }) => ({
        setUsageFilters: () => [
            router.values.location.pathname,
            {
                range: values.usageRange,
                granularity: values.usageGranularity,
                project_ids: values.selectedProjectIds.length ? values.selectedProjectIds.join(',') : undefined,
                breakdown_by_project: values.breakdownByProject ? 'true' : undefined,
            },
            router.values.hashParams,
            { replace: true },
        ],
    })),
    urlToAction(({ actions, values }) => ({
        [urls.organizationBillingRealTimeUsage()]: (_, searchParams) => {
            const filters = filtersFromParams(searchParams)
            if (
                filters.range !== values.usageRange ||
                filters.granularity !== values.usageGranularity ||
                filters.breakdownByProject !== values.breakdownByProject ||
                filters.projectIds.join(',') !== values.selectedProjectIds.join(',')
            ) {
                actions.setUsageFilters(filters)
            }
        },
    })),
    // One action covers both filters, so the mount reads the URL and loads exactly once.
    afterMount(({ actions }) => actions.setUsageFilters(filtersFromParams(router.values.searchParams))),
])
