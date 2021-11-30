import { kea } from "kea"
import { api } from "lib/api.mock"
import { Experiment } from "~/types"

export const experimentsLogic = kea<experimentsLogicType>({
    path: ['scenes', 'experiments', 'experimentsLogic'],
    loaders: ({ values }) => ({
        experiments: [
            null as Experiment | null,
            {
                loadExperiments: async () => {
                    const url = `api/projects/${values.currentTeamId}/experiments`
                    return await api.get(url)
                }
            }

        ]
    })
})