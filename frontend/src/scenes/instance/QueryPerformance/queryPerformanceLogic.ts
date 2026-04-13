import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import type { queryPerformanceLogicType } from './queryPerformanceLogicType'

export interface PrecomputationTeam {
    team_id: number
    team_name: string
    organization_name: string | null
    experiment_precomputation_enabled: boolean
}

export const queryPerformanceLogic = kea<queryPerformanceLogicType>([
    path(['scenes', 'instance', 'QueryPerformance', 'queryPerformanceLogic']),
    actions({
        setSearch: (search: string) => ({ search }),
        setPrecomputation: (teamId: number, enabled: boolean) => ({ teamId, enabled }),
    }),
    reducers({
        search: [
            '',
            {
                setSearch: (_, { search }) => search,
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
                    // Replace the updated team in the list
                    return values.precomputationTeams.map((team) => (team.team_id === updated.team_id ? updated : team))
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        setSearch: async ({ search }, breakpoint) => {
            // Debounce: wait 300ms, then reload
            await breakpoint(300)
            // If search is cleared, reload to show only enabled teams
            if (search || search === '') {
                actions.loadPrecomputationTeams()
            }
        },
    })),
    afterMount(({ actions }) => {
        if (userLogic.findMounted()?.values.user?.is_staff) {
            actions.loadPrecomputationTeams()
        }
    }),
])
