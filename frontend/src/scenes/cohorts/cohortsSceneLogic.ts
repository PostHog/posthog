import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { PaginationManual, Sorting } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { objectsEqual } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { personsLogic } from 'scenes/persons/personsLogic'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { processCohort } from '~/models/cohortsModel'
import { ActivityScope, Breadcrumb, CohortType, ExporterFormat } from '~/types'

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
    tabAwareScene(),
    connect(() => ({
        actions: [exportsLogic, ['startExport']],
    })),
    actions(() => ({
        setCohortFilters: (filters: Partial<CohortFilters>, replace?: boolean) => ({ filters, replace }),
        deleteCohort: (cohort: Partial<CohortType>) => ({ cohort }),
        exportCohortPersons: (id: CohortType['id'], columns?: string[]) => ({ id, columns }),
        setCohortSorting: (sorting: Sorting | null) => ({ sorting }),
    })),
    reducers({
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
        cohortSorting: [
            null as Sorting | null,
            {
                setCohortSorting: (_, { sorting }) => {
                    return sorting
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
                        iconType: 'cohort',
                    },
                ]
            },
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [],
            (): SidePanelSceneContext => ({
                activity_scope: ActivityScope.COHORT,
            }),
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
    listeners(({ actions, cache, values }) => ({
        loadCohortsSuccess: async ({ cohorts }: { cohorts: CountedPaginatedResponse<CohortType> }) => {
            const is_calculating = cohorts.results.filter((cohort) => cohort.is_calculating).length > 0
            if (!is_calculating || !router.values.location.pathname.includes(urls.cohorts())) {
                return
            }
            cache.disposables.add(() => {
                const timerId = window.setTimeout(actions.loadCohorts, POLL_TIMEOUT)
                return () => clearTimeout(timerId)
            }, 'pollTimeout')
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
    tabAwareActionToUrl(({ values }) => ({
        setCohortFilters: () => {
            const searchParams: Record<string, any> = { ...router.values.searchParams }

            if (values.cohortFilters.page != null) {
                searchParams['page'] = values.cohortFilters.page
            } else {
                delete searchParams['page']
            }

            if (values.cohortFilters.search != null) {
                searchParams['search'] = values.cohortFilters.search
            } else {
                delete searchParams['search']
            }

            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        },
        setCohortSorting: () => {
            const searchParams: Record<string, any> = { ...router.values.searchParams }

            if (values.cohortSorting != null) {
                searchParams['sorting'] = JSON.stringify(values.cohortSorting)
            } else {
                delete searchParams['sorting']
            }

            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        },
    })),
    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.cohorts()]: (_, searchParams) => {
            const { page, search, type, created_by_id, sorting } = searchParams
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

            let currentSorting = values.cohortSorting

            if (sorting != null) {
                try {
                    const parsedSorting = JSON.parse(sorting)
                    if (parsedSorting) {
                        currentSorting = parsedSorting
                    }
                } catch (error: any) {
                    console.error('Failed to parse sorting', error, { sorting })
                    posthog.captureException(error, {
                        extra: {
                            context: 'Failed to parse sorting',
                            sorting: sorting,
                        },
                    })
                }
            }

            actions.setCohortSorting(currentSorting)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadCohorts()
    }),
])
