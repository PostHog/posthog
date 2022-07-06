import { kea } from 'kea'
import api from 'lib/api'
import type { cohortsModelType } from './cohortsModelType'
import { CohortType, ExporterFormat } from '~/types'
import { personsLogic } from 'scenes/persons/personsLogic'
import { deleteWithUndo, processCohort } from 'lib/utils'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

const POLL_TIMEOUT = 5000

export const cohortsModel = kea<cohortsModelType>({
    path: ['models', 'cohortsModel'],
    connect: { values: [featureFlagLogic, ['featureFlags']] },
    actions: () => ({
        setPollTimeout: (pollTimeout: number | null) => ({ pollTimeout }),
        updateCohort: (cohort: CohortType) => ({ cohort }),
        deleteCohort: (cohort: Partial<CohortType>) => ({ cohort }),
        cohortCreated: (cohort: CohortType) => ({ cohort }),
        exportCohortPersons: (id: CohortType['id']) => ({ id }),
    }),

    loaders: () => ({
        cohorts: {
            __default: [] as CohortType[],
            loadCohorts: async () => {
                // TRICKY in tests this was returning undefined without calling list
                const response = await api.cohorts.list()
                personsLogic.findMounted({ syncWithUrl: true })?.actions.loadCohorts() // To ensure sync on person page
                return response?.results?.map((cohort) => processCohort(cohort)) || []
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
            deleteCohort: (state, { cohort }) => {
                if (!cohort.id) {
                    return state
                }
                return [...state].filter((c) => c.id !== cohort.id)
            },
        },
    },

    selectors: {
        cohortsWithAllUsers: [(s) => [s.cohorts], (cohorts) => [{ id: 'all', name: 'All Users*' }, ...cohorts]],
        cohortsById: [
            (s) => [s.cohorts],
            (cohorts): Partial<Record<string | number, CohortType>> =>
                Object.fromEntries(cohorts.map((cohort) => [cohort.id, cohort])),
        ],
    },

    listeners: ({ actions, values }) => ({
        loadCohortsSuccess: async ({ cohorts }: { cohorts: CohortType[] }) => {
            const is_calculating = cohorts.filter((cohort) => cohort.is_calculating).length > 0
            if (!is_calculating) {
                return
            }
            actions.setPollTimeout(window.setTimeout(actions.loadCohorts, POLL_TIMEOUT))
        },
        exportCohortPersons: async ({ id }) => {
            if (!!values.featureFlags[FEATURE_FLAGS.ASYNC_EXPORT_CSV_FOR_LIVE_EVENTS]) {
                await triggerExport({
                    export_format: ExporterFormat.CSV,
                    export_context: {
                        path: `/api/cohort/${id}/persons`,
                    },
                })
            } else {
                window.open(`/api/person.csv?cohort=${id}`, '_blank')
            }
        },
        deleteCohort: ({ cohort }) => {
            deleteWithUndo({
                endpoint: api.cohorts.determineDeleteEndpoint(),
                object: cohort,
                callback: actions.loadCohorts,
            })
        },
    }),

    events: ({ actions, values }) => ({
        afterMount: actions.loadCohorts,
        beforeUnmount: () => {
            clearTimeout(values.pollTimeout || undefined)
        },
    }),
})
