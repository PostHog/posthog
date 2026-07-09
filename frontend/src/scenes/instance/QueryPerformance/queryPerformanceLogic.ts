import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import type { queryPerformanceLogicType } from './queryPerformanceLogicType'

export interface PrecomputationTeam {
    team_id: number
    team_name: string
    organization_id: string | null
    organization_name: string | null
    organization_arr: number | null
    experiment_precomputation_enabled: boolean
}

export type ExperimentsTab = 'slowest_queries' | 'precompute_overview' | 'cache_health'

export interface PrecomputePathStats {
    reads: number
    failed_reads: number
    // Reads where precompute was attempted (no skip reason). On the direct_scan path these paid
    // for the build AND the full events scan — the failure bucket to watch.
    attempted: number
    skip_reasons: Record<string, number>
    avg_duration_ms: number | null
    p50_duration_ms: number | null
    p90_duration_ms: number | null
    avg_read_bytes: number | null
    total_read_bytes: number
}

export interface PrecomputeBuildStats {
    total: number
    succeeded: number
    failed: number
    total_duration_ms: number
    total_read_bytes: number
    // Optional: responses served by a backend from before these fields existed omit them.
    failed_duration_ms?: number
    failed_read_bytes?: number
    by_table: Record<string, { succeeded: number; failed: number }>
    failures_by_code: Record<string, number>
}

export interface PrecomputeJobStats {
    ready: number
    failed: number
    pending: number
    stale_failed: number
    stuck_pending: number
}

export interface PrecomputeOverviewResponse {
    hours: number
    reads: {
        total: number
        failed: number
        by_exposures_path: Record<string, PrecomputePathStats>
        metric_events: { precomputed: number; direct_scan: number; not_applicable: number }
    }
    builds: PrecomputeBuildStats
    jobs: PrecomputeJobStats
}

export interface CachePartitionStats {
    partition: string // YYYYMMDD — the expiry day of the partition (tables partition by toYYYYMMDD(expires_at))
    rows: number
    bytes_on_disk: number
    parts: number
}

export interface CacheTableStats {
    table: string
    total_rows: number
    bytes_on_disk: number
    active_parts: number
    partition_count: number
    oldest_partition: string | null
    newest_partition: string | null
    partitions: CachePartitionStats[]
}

export interface CacheHealthResponse {
    tables: CacheTableStats[]
}

// One row of the partition breakdown table: a single expiry day, with each cache table's stats for that day.
export interface CachePartitionRow {
    partition: string
    perTable: Record<string, CachePartitionStats>
}

export interface SlowestQuery {
    query_id: string
    query: string
    timestamp: string
    execution_time: number
    exception: string
    status: number
    team_id: number
    team_name: string | null
    organization_name: string | null
    organization_arr: number | null
    query_type: string
    experiment_name: string
    experiment_metric_name: string
    experiment_execution_path: string
    experiment_exposures_path: string
    experiment_metric_events_path: string
    experiment_query_surface: string
    experiment_precompute_table: string
    experiment_precompute_skip_reason: string
    experiment_scan_date_from: string
    experiment_scan_date_to: string
    precompute_window_start: string
    precompute_window_end: string
    experiment_query_group_id: string
    experiment_metric_type: string
    experiment_funnel_order_type: string | null
    experiment_id: number | null
    total_duration_ms: number
    read_bytes: number
    read_rows: number
    exception_code: number
    memory_usage: number
    sub_queries: SlowestQuery[]
}

export const queryPerformanceLogic = kea<queryPerformanceLogicType>([
    path(['scenes', 'instance', 'QueryPerformance', 'queryPerformanceLogic']),
    actions({
        setSearch: (search: string) => ({ search }),
        setPrecomputation: (teamId: number, enabled: boolean) => ({ teamId, enabled }),
        setHoursBack: (hours: number) => ({ hours }),
        setTeamIdFilter: (teamId: string) => ({ teamId }),
        setExperimentIdFilter: (experimentId: string) => ({ experimentId }),
        setMetricTypeFilter: (metricType: string) => ({ metricType }),
        setExceptionCodeFilter: (exceptionCode: string) => ({ exceptionCode }),
        setExperimentsTab: (tab: ExperimentsTab) => ({ tab }),
        setOverviewHoursBack: (hours: number) => ({ hours }),
    }),
    reducers({
        search: [
            '',
            {
                setSearch: (_, { search }) => search,
            },
        ],
        hoursBack: [
            1,
            {
                setHoursBack: (_, { hours }) => hours,
            },
        ],
        teamIdFilter: [
            '',
            {
                setTeamIdFilter: (_, { teamId }) => teamId,
            },
        ],
        experimentIdFilter: [
            '',
            {
                setExperimentIdFilter: (_, { experimentId }) => experimentId,
            },
        ],
        metricTypeFilter: [
            '',
            {
                setMetricTypeFilter: (_, { metricType }) => metricType,
            },
        ],
        exceptionCodeFilter: [
            '',
            {
                setExceptionCodeFilter: (_, { exceptionCode }) => exceptionCode,
            },
        ],
        experimentsTab: [
            'slowest_queries' as ExperimentsTab,
            {
                setExperimentsTab: (_, { tab }) => tab,
            },
        ],
        overviewHoursBack: [
            24,
            {
                setOverviewHoursBack: (_, { hours }) => hours,
            },
        ],
    }),
    loaders(({ values }) => ({
        precomputationTeams: [
            [] as PrecomputationTeam[],
            {
                loadPrecomputationTeams: async () => {
                    const params = new URLSearchParams()
                    if (values.search) {
                        params.append('search', values.search)
                    }
                    return await api.get(`api/debug_ch_queries/precomputation_teams/?${params.toString()}`)
                },
                setPrecomputation: async ({ teamId, enabled }) => {
                    const updated: PrecomputationTeam = await api.create('api/debug_ch_queries/precomputation_teams/', {
                        team_id: teamId,
                        experiment_precomputation_enabled: enabled,
                    })
                    const updatedList = values.precomputationTeams.map((team) =>
                        team.team_id === updated.team_id ? updated : team
                    )
                    // If no search active, filter out disabled teams to match backend default
                    return values.search
                        ? updatedList
                        : updatedList.filter((team) => team.experiment_precomputation_enabled)
                },
            },
        ],
        cacheHealth: [
            null as CacheHealthResponse | null,
            {
                loadCacheHealth: async () => {
                    return await api.get('api/debug_ch_queries/cache_health/')
                },
            },
        ],
        precomputeOverview: [
            null as PrecomputeOverviewResponse | null,
            {
                loadPrecomputeOverview: async () => {
                    return await api.get(`api/debug_ch_queries/precompute_overview/?hours=${values.overviewHoursBack}`)
                },
            },
        ],
        slowestQueries: [
            [] as SlowestQuery[],
            {
                loadSlowestQueries: async () => {
                    const params = new URLSearchParams({ hours: String(values.hoursBack) })
                    if (values.teamIdFilter) {
                        params.append('team_id', values.teamIdFilter)
                    }
                    if (values.experimentIdFilter) {
                        params.append('experiment_id', values.experimentIdFilter)
                    }
                    if (values.metricTypeFilter) {
                        // Encoded as "<metricType>" or "funnel:<orderType>" (e.g. "funnel:ordered").
                        const [metricType, funnelOrderType] = values.metricTypeFilter.split(':')
                        params.append('metric_type', metricType)
                        if (funnelOrderType) {
                            params.append('funnel_order_type', funnelOrderType)
                        }
                    }
                    if (values.exceptionCodeFilter) {
                        params.append('exception_code', values.exceptionCodeFilter)
                    }
                    return await api.get(`api/debug_ch_queries/slowest_queries/?${params.toString()}`)
                },
            },
        ],
    })),
    selectors({
        cachePartitionRows: [
            (s) => [s.cacheHealth],
            (cacheHealth): CachePartitionRow[] => {
                const byPartition: Record<string, CachePartitionRow> = {}
                for (const table of cacheHealth?.tables ?? []) {
                    for (const partition of table.partitions) {
                        const row = (byPartition[partition.partition] ??= {
                            partition: partition.partition,
                            perTable: {},
                        })
                        row.perTable[table.table] = partition
                    }
                }
                return Object.values(byPartition).sort((a, b) => a.partition.localeCompare(b.partition))
            },
        ],
    }),
    listeners(({ actions }) => ({
        setSearch: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadPrecomputationTeams()
        },
        setHoursBack: () => {
            actions.loadSlowestQueries()
        },
        setTeamIdFilter: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadSlowestQueries()
        },
        setExperimentIdFilter: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadSlowestQueries()
        },
        setMetricTypeFilter: () => {
            actions.loadSlowestQueries()
        },
        setExceptionCodeFilter: () => {
            actions.loadSlowestQueries()
        },
        setOverviewHoursBack: () => {
            actions.loadPrecomputeOverview()
        },
    })),
    afterMount(({ actions }) => {
        if (userLogic.findMounted()?.values.user?.is_staff) {
            actions.loadPrecomputationTeams()
            actions.loadSlowestQueries()
            actions.loadCacheHealth()
            actions.loadPrecomputeOverview()
        }
    }),
])
