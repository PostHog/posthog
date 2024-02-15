import Fuse from 'fuse.js'
import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'
import { personsLogic } from 'scenes/persons/personsLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    AnyCohortCriteriaType,
    BehavioralCohortType,
    BehavioralEventType,
    CohortCriteriaGroupFilter,
    CohortType,
    ExporterFormat,
} from '~/types'

import type { cohortsModelType } from './cohortsModelType'

const POLL_TIMEOUT = 5000

export function processCohort(cohort: CohortType): CohortType {
    return {
        ...cohort,
        ...{
            /* Populate value_property with value and overwrite value with corresponding behavioral filter type */
            filters: {
                properties: {
                    ...cohort.filters.properties,
                    values: (cohort.filters.properties?.values?.map((group) =>
                        'values' in group
                            ? {
                                  ...group,
                                  values: (group.values as AnyCohortCriteriaType[]).map((c) =>
                                      c.type &&
                                      [BehavioralFilterKey.Cohort, BehavioralFilterKey.Person].includes(c.type) &&
                                      !('value_property' in c)
                                          ? {
                                                ...c,
                                                value_property: c.value,
                                                value:
                                                    c.type === BehavioralFilterKey.Cohort
                                                        ? BehavioralCohortType.InCohort
                                                        : BehavioralEventType.HaveProperty,
                                            }
                                          : c
                                  ),
                              }
                            : group
                    ) ?? []) as CohortCriteriaGroupFilter[] | AnyCohortCriteriaType[],
                },
            },
        },
    }
}

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
            cohortCreated: (state, { cohort }) => {
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

        cohortsSearch: [
            (s) => [s.cohorts],
            (cohorts): ((term: string) => CohortType[]) => {
                const fuse = new Fuse<CohortType>(cohorts ?? [], {
                    keys: ['name'],
                    threshold: 0.3,
                })

                return (term) => fuse.search(term).map((result) => result.item)
            },
        ],
    }),
    listeners(({ actions }) => ({
        loadCohortsSuccess: async ({ cohorts }: { cohorts: CohortType[] }) => {
            const is_calculating = cohorts.filter((cohort) => cohort.is_calculating).length > 0
            if (!is_calculating || !window.location.pathname.includes(urls.cohorts())) {
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
        deleteCohort: async ({ cohort }) => {
            await deleteWithUndo({
                endpoint: api.cohorts.determineDeleteEndpoint(),
                object: cohort,
                callback: actions.loadCohorts,
            })
        },
    })),
    beforeUnmount(({ values }) => {
        clearTimeout(values.pollTimeout || undefined)
    }),

    afterMount(({ actions, values }) => {
        if (isAuthenticatedTeam(values.currentTeam)) {
            // Don't load on shared insights/dashboards
            actions.loadCohorts()
        }
    }),
    permanentlyMount(),
])
