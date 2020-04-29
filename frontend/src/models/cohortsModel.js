import { kea } from 'kea'
import api from 'lib/api'

export const cohortsModel = kea({
    loaders: () => ({
        cohorts: {
            loadCohorts: async () => {
                const response = await api.get('api/cohort')
                return response.results
            },
        },
    }),

    events: ({ actions }) => ({
        afterMount: actions.loadCohorts,
    }),
})
