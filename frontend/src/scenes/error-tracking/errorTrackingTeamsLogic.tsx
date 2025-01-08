import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { ErrorTrackingTeam } from 'lib/components/Errors/types'

import type { errorTrackingTeamsLogicType } from './errorTrackingTeamsLogicType'

export const errorTrackingTeamsLogic = kea<errorTrackingTeamsLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingTeamsLogic']),

    loaders(({ values }) => ({
        teams: [
            [] as ErrorTrackingTeam[],
            {
                loadTeams: async () => {
                    const response = await api.errorTracking.teams()
                    return response.results
                },
                deleteTeam: async (id) => {
                    await api.errorTracking.deleteTeam(id)
                    const newValues = [...values.teams]
                    return newValues.filter((v) => v.id !== id)
                },
            },
        ],
    })),
])
