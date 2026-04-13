import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import type { queryPerformanceLogicType } from './queryPerformanceLogicType'

export interface PrecomputationTeam {
    team_id: number
    team_name: string
    organization_name: string | null
}

export const queryPerformanceLogic = kea<queryPerformanceLogicType>([
    path(['scenes', 'instance', 'QueryPerformance', 'queryPerformanceLogic']),
    loaders({
        precomputationTeams: [
            [] as PrecomputationTeam[],
            {
                loadPrecomputationTeams: async () => {
                    return await api.get('api/debug_ch_queries/precomputation_teams/')
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        if (userLogic.findMounted()?.values.user?.is_staff) {
            actions.loadPrecomputationTeams()
        }
    }),
])
