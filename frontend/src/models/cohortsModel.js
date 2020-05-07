import { kea } from 'kea'
import api from 'lib/api'

const POLL_TIMEOUT = 5000

export const cohortsModel = kea({
    actions: () => ({
        setPollTimeout: pollTimeout => ({ pollTimeout }),
        pollCohorts: true,
    }),

    loaders: () => ({
        cohorts: {
            loadCohorts: async () => {
                const response = await api.get('api/cohort')
                return response.results
            },
        },
    }),

    reducers: () => ({
        pollTimeout: [
            null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
    }),

    listeners: ({ actions, sharedListeners }) => ({
        loadCohortsSuccess: sharedListeners.pollCohorts,
        pollCohorts: async () => {
            const response = await api.get('api/cohort')
            actions.loadCohortsSuccess(response.results)
            sharedListeners.pollCohorts({ cohorts: response.results })
        },
    }),

    sharedListeners: ({ actions }) => ({
        pollCohorts: ({ cohorts }) => {
            const is_calculating = cohorts.filter(cohort => cohort.is_calculating).length > 0
            if (!is_calculating) return
            actions.setPollTimeout(setTimeout(actions.pollCohorts, POLL_TIMEOUT))
        },
    }),

    events: ({ actions, values }) => ({
        afterMount: actions.loadCohorts,
        beforeUnmount: () => {
            clearTimeout(values.pollTimeout)
        },
    }),
})
