import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
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
                    return await api.get(`api/debug_ch_queries/slowest_queries/?${params.toString()}`)
                },
            },
        ],
    })),
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
    })),
    afterMount(({ actions }) => {
        if (userLogic.findMounted()?.values.user?.is_staff) {
            actions.loadPrecomputationTeams()
            actions.loadSlowestQueries()
        }
    }),
])
