import { loaders } from 'kea-loaders'
import { kea, path, connect, actions, reducers, selectors, listeners, events } from 'kea'
import api from 'lib/api'
import type { cohortsModelType } from './cohortsModelType'
import { CohortType, ExporterFormat } from '~/types'
import { personsLogic } from 'scenes/persons/personsLogic'
import { deleteWithUndo, processCohort } from 'lib/utils'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'

const POLL_TIMEOUT = 5000

export const cohortsModel = kea<cohortsModelType>([
    path(['models', 'cohortsModel']),
    connect({
        values: [teamLogic, ['currentTeam']],
    }),
    actions(() => ({
        setPollTimeout: (pollTimeout: number | null) => ({ pollTimeout }),
        updateCohort: (cohort: CohortType) => ({ cohort }),
        deleteCohort: (cohort: Partial<CohortType>) => ({ cohort }),
        cohortCreated: (cohort: CohortType) => ({ cohort }),
        exportCohortPersons: (id: CohortType['id'], columns?: string[]) => ({ id, columns }),
    })),
    loaders(() => ({
        cohorts: {
            __default: [] as CohortType[],
            loadCohorts: async () => {
                // TRICKY in tests this was returning undefined without calling list
                const response = await api.cohorts.list()
                personsLogic.findMounted({ syncWithUrl: true })?.actions.loadCohorts() // To ensure sync on person page
                return response?.results?.map((cohort) => processCohort(cohort)) || []
            },
        },
    })),
    reducers({
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
                return [...state].map((existingCohort) => (existingCohort.id === cohort.id ? cohort : existingCohort))
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
    }),
    selectors({
        cohortsWithAllUsers: [(s) => [s.cohorts], (cohorts) => [{ id: 'all', name: 'All Users*' }, ...cohorts]],
        cohortsById: [
            (s) => [s.cohorts],
            (cohorts): Partial<Record<string | number, CohortType>> =>
                Object.fromEntries(cohorts.map((cohort) => [cohort.id, cohort])),
        ],
    }),
    listeners(({ actions }) => ({
        loadCohortsSuccess: async ({ cohorts }: { cohorts: CohortType[] }) => {
            const is_calculating = cohorts.filter((cohort) => cohort.is_calculating).length > 0
            if (!is_calculating) {
                return
            }
            actions.setPollTimeout(window.setTimeout(actions.loadCohorts, POLL_TIMEOUT))
        },
        exportCohortPersons: async ({ id, columns }) => {
            const exportCommand = {
                export_format: ExporterFormat.CSV,
                export_context: {
                    path: `/api/cohort/${id}/persons`,
                },
            }
            if (columns && columns.length > 0) {
                exportCommand.export_context['columns'] = columns
            }
            await triggerExport(exportCommand)
        },
        deleteCohort: ({ cohort }) => {
            deleteWithUndo({
                endpoint: api.cohorts.determineDeleteEndpoint(),
                object: cohort,
                callback: actions.loadCohorts,
            })
        },
    })),
    events(({ actions, values }) => ({
        afterMount: () => {
            if (isAuthenticatedTeam(values.currentTeam)) {
                // Don't load on shared insights/dashboards
                actions.loadCohorts()
            }
        },
        beforeUnmount: () => {
            clearTimeout(values.pollTimeout || undefined)
        },
    })),
])
