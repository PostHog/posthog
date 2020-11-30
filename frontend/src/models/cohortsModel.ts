import { kea } from 'kea'
import api from 'lib/api'
import { cohortsModelType } from './cohortsModelType'
import { CohortType } from '~/types'
import { toast } from 'react-toastify'

const POLL_TIMEOUT = 5000

export const cohortsModel = kea<cohortsModelType<CohortType>>({
    actions: () => ({
        setPollTimeout: (pollTimeout: NodeJS.Timeout | null) => ({ pollTimeout }),
    }),

    loaders: () => ({
        cohorts: {
            __default: [] as CohortType[],
            loadCohorts: async () => {
                const response = await api.get('api/cohort')
                return response.results
            },
            updateCohort: async (cohort) => {
                try {
                    return await api.update('api/cohort/' + cohort.id, cohort)
                } catch (err) {
                    if (err[0] === 'key-exists') {
                        toast.error('A feature flag with that key already exists')
                        return false
                    } else {
                        throw err
                    }
                }
            },
            createCohort: async (cohort) => {
                let create
                try {
                    create = await api.create('api/feature_flag/', cohort)
                } catch (err) {
                    if (err[0] === 'key-exists') {
                        toast.error('A feature flag with that key already exists')
                        return null
                    } else {
                        throw err
                    }
                }
                return create
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
        cohorts: {
            updateCohort: (state, cohort) => {
                if (!cohort) {
                    return null
                }
                return [...state].map((flag) => (flag.id === cohort.id ? cohort : flag))
            },
            updateCohortSuccess: (state) => state,
            createCohortSuccess: (state, { cohorts }) => {
                if (!cohorts) {
                    return state
                }
                return [cohorts, ...state]
            },
            deleteCohort: (state, cohort) => {
                if (!cohort) {
                    return null
                }
                return [...state].filter((flag) => flag.id !== cohort.id)
            },
            deleteCohortSuccess: (state) => state,
        },
    }),

    listeners: ({ actions }) => ({
        loadCohortsSuccess: async ({ cohorts }: { cohorts: CohortType[] }) => {
            const is_calculating = cohorts.filter((cohort) => cohort.is_calculating).length > 0
            if (!is_calculating) {
                return
            }
            actions.setPollTimeout(setTimeout(actions.loadCohorts, POLL_TIMEOUT))
        },
    }),

    events: ({ actions, values }) => ({
        afterMount: actions.loadCohorts,
        beforeUnmount: () => {
            clearTimeout(values.pollTimeout || undefined)
        },
    }),
})
