import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { PaginationManual } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { objectsEqual } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { personsLogic } from 'scenes/persons/personsLogic'
import { urls } from 'scenes/urls'

import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { processCohort } from '~/models/cohortsModel'
import { Breadcrumb, CohortType, ExporterFormat } from '~/types'

import type { cohortsSceneLogicType } from './cohortsSceneLogicType'

export interface CohortFilters {
    search?: string
    page?: number
    type?: 'static' | 'dynamic'
    created_by_id?: number
}

const POLL_TIMEOUT = 5000

const DEFAULT_COHORT_FILTERS: CohortFilters = {
    search: undefined,
    page: 1,
    type: undefined,
    created_by_id: undefined,
}

const COHORTS_PER_PAGE = 100

export const cohortsSceneLogic = kea<cohortsSceneLogicType>([
    path(['scenes', 'cohorts', 'cohortsSceneLogic']),
    connect(() => ({
        actions: [exportsLogic, ['startExport']],
    })),
    actions(() => ({
        setCohortFilters: (filters: Partial<CohortFilters>, replace?: boolean) => ({ filters, replace }),
        deleteCohort: (cohort: Partial<CohortType>) => ({ cohort }),
        exportCohortPersons: (id: CohortType['id'], columns?: string[]) => ({ id, columns }),
        setPollTimeout: (pollTimeout: number | null) => ({ pollTimeout }),
    })),
    reducers({
        pollTimeout: [
            null as number | null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
        cohortFilters: [
            DEFAULT_COHORT_FILTERS,
            {
                setCohortFilters: (state, { filters, replace }) => {
                    if (replace) {
                        return { ...DEFAULT_COHORT_FILTERS, ...filters }
                    }
                    return { ...state, ...filters }
                },
            },
        ],
        cohorts: [
            { count: 0, results: [] },
            {
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
        ],
    }),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        key: 'cohorts',
                        name: 'Cohorts',
                        path: urls.cohorts(),
                    },
                ]
            },
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
        shouldShowEmptyState: [
            (s) => [s.cohorts, s.cohortFilters],
            (cohorts: CountedPaginatedResponse<CohortType>, filters: CohortFilters): boolean => {
                return cohorts.results.length === 0 && objectsEqual(filters, DEFAULT_COHORT_FILTERS)
            },
        ],
    }),
    loaders(({ values }) => ({
        cohorts: [
            {
                count: 0,
                results: [],
                filters: DEFAULT_COHORT_FILTERS,
                offset: 0,
            } as CountedPaginatedResponse<CohortType>,
            {
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
        ],
    })),
    listeners(({ actions, values }) => ({
        loadCohortsSuccess: async ({ cohorts }: { cohorts: CountedPaginatedResponse<CohortType> }) => {
            const is_calculating = cohorts.results.filter((cohort) => cohort.is_calculating).length > 0
            if (!is_calculating || !router.values.location.pathname.includes(urls.cohorts())) {
                return
            }
            actions.setPollTimeout(window.setTimeout(actions.loadCohorts, POLL_TIMEOUT))
        },
        setCohortFilters: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadCohorts()
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
        exportCohortPersons: async ({ id, columns }) => {
            const cohort = values.cohorts.results.find((c) => c.id === id)
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
            const { page, search, type, created_by_id } = searchParams
            const filtersFromUrl: Partial<CohortFilters> = {
                search,
                type,
            }

            if (page !== undefined) {
                filtersFromUrl.page = parseInt(page)
            }
            if (created_by_id !== undefined) {
                filtersFromUrl.created_by_id = parseInt(created_by_id)
            }

            actions.setCohortFilters({ ...DEFAULT_COHORT_FILTERS, ...filtersFromUrl }, true)
        },
    })),
    beforeUnmount(({ values }) => {
        clearTimeout(values.pollTimeout || undefined)
    }),
    afterMount(({ actions }) => {
        actions.loadCohorts()
    }),
])
