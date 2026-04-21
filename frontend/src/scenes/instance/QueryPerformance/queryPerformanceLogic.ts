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
    organization_mrr: number | null
    query_type: string
    experiment_name: string
    experiment_metric_name: string
    experiment_execution_path: string
    experiment_metric_type: string
}

export const queryPerformanceLogic = kea<queryPerformanceLogicType>([
    path(['scenes', 'instance', 'QueryPerformance', 'queryPerformanceLogic']),
    actions({
        setSearch: (search: string) => ({ search }),
        setPrecomputation: (teamId: number, enabled: boolean) => ({ teamId, enabled }),
        setHoursBack: (hours: number) => ({ hours }),
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
                    return await api.get(`api/debug_ch_queries/slowest_queries/?hours=${values.hoursBack}`)
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
    })),
    afterMount(({ actions }) => {
        if (userLogic.findMounted()?.values.user?.is_staff) {
            actions.loadPrecomputationTeams()
            actions.loadSlowestQueries()
        }
    }),
])
