import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api, { CountedPaginatedResponse } from 'lib/api'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { v4 as uuidv4 } from 'uuid'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { COHORT_EVENT_TYPES_WITH_EXPLICIT_DATETIME } from 'scenes/cohorts/CohortFilters/constants'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'
import { personsLogic } from 'scenes/persons/personsLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
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

export const COHORTS_PER_PAGE = 100

export const MAX_COHORTS_FOR_FULL_LIST = 2000

export interface CohortFilters {
    search?: string
    page?: number
}

export const DEFAULT_COHORT_FILTERS: CohortFilters = {
    search: undefined,
    page: 1,
}

export function processCohort(cohort: CohortType): CohortType {
    return {
        ...cohort,

        /* Populate value_property with value and overwrite value with corresponding behavioral filter type */
        filters: {
            properties: {
                ...cohort.filters.properties,
                values: (cohort.filters.properties?.values?.map((group) =>
                    'values' in group
                        ? {
                              ...group,
                              values: (group.values as AnyCohortCriteriaType[]).map((c) => processCohortCriteria(c)),
                          }
                        : group
                ) ?? []) as CohortCriteriaGroupFilter[] | AnyCohortCriteriaType[],
            },
        },
    }
}

function convertTimeValueToRelativeTime(criteria: AnyCohortCriteriaType): string | undefined {
    const timeValue = criteria?.time_value
    const timeInterval = criteria?.time_interval

    if (timeValue && timeInterval) {
        return `-${timeValue}${timeInterval[0]}`
    }
}

function processCohortCriteria(criteria: AnyCohortCriteriaType): AnyCohortCriteriaType {
    if (!criteria.type) {
        return criteria
    }

    const processedCriteria = { ...criteria }

    if (
        [BehavioralFilterKey.Cohort, BehavioralFilterKey.Person].includes(criteria.type) &&
        !('value_property' in criteria)
    ) {
        processedCriteria.value_property = criteria.value
        processedCriteria.value =
            criteria.type === BehavioralFilterKey.Cohort
                ? BehavioralCohortType.InCohort
                : BehavioralEventType.HaveProperty
    }

    if (
        [BehavioralFilterKey.Behavioral].includes(criteria.type) &&
        !('explicit_datetime' in criteria) &&
        criteria.value &&
        COHORT_EVENT_TYPES_WITH_EXPLICIT_DATETIME.includes(criteria.value)
    ) {
        processedCriteria.explicit_datetime = convertTimeValueToRelativeTime(criteria)
    }

    if (processedCriteria.sort_key == null) {
        processedCriteria.sort_key = uuidv4()
    }

    return processedCriteria
}

export const cohortsModel = kea<cohortsModelType>([
    path(['models', 'cohortsModel']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
        actions: [exportsLogic, ['startExport']],
    })),
    actions(() => ({
        setPollTimeout: (pollTimeout: number | null) => ({ pollTimeout }),
        updateCohort: (cohort: CohortType) => ({ cohort }),
        deleteCohort: (cohort: Partial<CohortType>) => ({ cohort }),
        cohortCreated: (cohort: CohortType) => ({ cohort }),
        exportCohortPersons: (id: CohortType['id'], columns?: string[]) => ({ id, columns }),
        setCohortFilters: (filters: Partial<CohortFilters>) => ({ filters }),
    })),
    loaders(({ values }) => ({
        cohorts: {
            __default: { count: 0, results: [] } as CountedPaginatedResponse<CohortType>,
            loadCohorts: async () => {
                const response = await api.cohorts.listPaginated({
                    ...values.paramsFromFilters,
                })
                personsLogic.findMounted({ syncWithUrl: true })?.actions.loadCohorts()
                return {
                    count: response.count,
                    results: response.results.map((cohort) => processCohort(cohort)),
                }
            },
        },
        allCohorts: {
            __default: { count: 0, results: [] } as CountedPaginatedResponse<CohortType>,
            loadAllCohorts: async () => {
                const response = await api.cohorts.listPaginated({
                    limit: MAX_COHORTS_FOR_FULL_LIST,
                })
                return {
                    count: response.count,
                    results: response.results.map((cohort) => processCohort(cohort)),
                }
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
                return {
                    ...state,
                    results: state.results.map((existingCohort) =>
                        existingCohort.id === cohort.id ? cohort : existingCohort
                    ),
                }
            },
            cohortCreated: (state, { cohort }) => {
                if (!cohort) {
                    return state
                }
                return {
                    ...state,
                    results: [cohort, ...state.results],
                }
            },
            deleteCohort: (state, { cohort }) => {
                if (!cohort.id) {
                    return state
                }
                return {
                    ...state,
                    results: state.results.filter((c) => c.id !== cohort.id),
                }
            },
        },
        cohortFilters: [
            DEFAULT_COHORT_FILTERS,
            {
                setCohortFilters: (state, { filters }) => {
                    return { ...state, ...filters }
                },
            },
        ],
    }),
    selectors({
        cohortsById: [
            (s) => [s.allCohorts],
            (allCohorts): Partial<Record<string | number, CohortType>> =>
                Object.fromEntries(allCohorts.results.map((cohort) => [cohort.id, cohort])),
        ],
        count: [(selectors) => [selectors.cohorts], (cohorts) => cohorts.count],
        paramsFromFilters: [
            (s) => [s.cohortFilters],
            (filters: CohortFilters) => ({
                ...filters,
                limit: COHORTS_PER_PAGE,
                offset: filters.page ? (filters.page - 1) * COHORTS_PER_PAGE : 0,
            }),
        ],
        pagination: [
            (s) => [s.cohortFilters, s.count],
            (filters, count): PaginationManual => {
                return {
                    controlled: true,
                    pageSize: COHORTS_PER_PAGE,
                    currentPage: filters.page || 1,
                    entryCount: count,
                }
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        loadCohortsSuccess: async ({ cohorts }: { cohorts: CountedPaginatedResponse<CohortType> }) => {
            const is_calculating = cohorts.results.filter((cohort) => cohort.is_calculating).length > 0
            if (!is_calculating || !router.values.location.pathname.includes(urls.cohorts())) {
                return
            }
            actions.setPollTimeout(window.setTimeout(actions.loadCohorts, POLL_TIMEOUT))
        },
        loadAllCohortsSuccess: async ({ allCohorts }: { allCohorts: CountedPaginatedResponse<CohortType> }) => {
            const is_calculating = allCohorts.results.filter((cohort) => cohort.is_calculating).length > 0
            if (!is_calculating || !router.values.location.pathname.includes(urls.cohorts())) {
                return
            }
            actions.setPollTimeout(window.setTimeout(actions.loadAllCohorts, POLL_TIMEOUT))
        },
        exportCohortPersons: async ({ id, columns }) => {
            const cohort = values.cohortsById[id]
            const exportCommand = {
                export_format: ExporterFormat.CSV,
                export_context: {
                    path: `/api/cohort/${id}/persons`,
                    columns,
                    filename: cohort?.name ? `cohort-${cohort.name}` : 'cohort',
                } as { path: string; columns?: string[]; filename?: string },
            }
            if (columns && columns.length > 0) {
                exportCommand.export_context['columns'] = columns
            }
            actions.startExport(exportCommand)
        },
        deleteCohort: async ({ cohort }) => {
            await deleteWithUndo({
                endpoint: api.cohorts.determineDeleteEndpoint(),
                object: cohort,
                callback: (undo) => {
                    actions.loadCohorts()
                    if (cohort.id && cohort.id !== 'new') {
                        if (undo) {
                            refreshTreeItem('cohort', String(cohort.id))
                        } else {
                            deleteFromTree('cohort', String(cohort.id))
                        }
                    }
                },
            })
        },
        setCohortFilters: async () => {
            if (!router.values.location.pathname.includes(urls.cohorts())) {
                return
            }
            actions.loadCohorts()
        },
    })),
    actionToUrl(({ values }) => ({
        setCohortFilters: () => {
            const searchParams: Record<string, any> = {
                ...values.cohortFilters,
            }

            // Only include non-default values in URL
            Object.keys(searchParams).forEach((key) => {
                if (
                    searchParams[key] === undefined ||
                    searchParams[key] === DEFAULT_COHORT_FILTERS[key as keyof CohortFilters]
                ) {
                    delete searchParams[key]
                }
            })

            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        },
    })),
    urlToAction(({ actions }) => ({
        [urls.cohorts()]: (_, searchParams) => {
            const { page, search } = searchParams
            const filtersFromUrl: Partial<CohortFilters> = {
                search,
            }

            filtersFromUrl.page = page !== undefined ? parseInt(page) : undefined

            actions.setCohortFilters({ ...DEFAULT_COHORT_FILTERS, ...filtersFromUrl })
        },
    })),
    beforeUnmount(({ values }) => {
        clearTimeout(values.pollTimeout || undefined)
    }),
    afterMount(({ actions, values }) => {
        if (isAuthenticatedTeam(values.currentTeam)) {
            // Don't load on shared insights/dashboards
            actions.loadAllCohorts()
        }
    }),
    permanentlyMount(),
])
