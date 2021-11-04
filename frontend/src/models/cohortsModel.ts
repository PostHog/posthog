import { kea } from 'kea'
import api from 'lib/api'
import { cohortsModelType } from './cohortsModelType'
import { CohortType } from '~/types'

const POLL_TIMEOUT = 5000

export const cohortsModel = kea<cohortsModelType>({
    actions: () => ({
        setPollTimeout: (pollTimeout: number | null) => ({ pollTimeout }),
        updateCohort: (cohort: CohortType) => ({ cohort }),
        cohortCreated: (cohort: CohortType) => ({ cohort }),
    }),

    loaders: () => ({
        cohorts: {
            __default: [] as CohortType[],
            loadCohorts: async () => {
                const response = await api.cohorts.list()
                return response.results
            },
        },
    }),

    reducers: {
        pollTimeout: [
            null as number | null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
        cohorts: {
            updateCohort: (state, { cohort }) => {
                if (!cohort) {
                    return state
                }
                return [...state].map((flag) => (flag.id === cohort.id ? cohort : flag))
            },
            cohortCreated: (state = [], { cohort }) => {
                if (!cohort) {
                    return state
                }
                return [cohort, ...state]
            },
            deleteCohort: (state, cohort) => {
                if (!cohort) {
                    return state
                }
                return [...state].filter((flag) => flag.id !== cohort.id)
            },
            deleteCohortSuccess: (state) => state,
        },
    },

    selectors: {
        cohortsWithAllUsers: [(s) => [s.cohorts], (cohorts) => [{ id: 'all', name: 'All Users*' }, ...cohorts]],
    },

    listeners: ({ actions }) => ({
        loadCohortsSuccess: async ({ cohorts }: { cohorts: CohortType[] }) => {
            const is_calculating = cohorts.filter((cohort) => cohort.is_calculating).length > 0
            if (!is_calculating) {
                return
            }
            actions.setPollTimeout(window.setTimeout(actions.loadCohorts, POLL_TIMEOUT))
        },
    }),

    events: ({ actions, values }) => ({
        afterMount: actions.loadCohorts,
        beforeUnmount: () => {
            clearTimeout(values.pollTimeout || undefined)
        },
    }),
})
