import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { PaginationManual } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'

import { CohortType } from '~/types'

import type { saveToCohortModalContentLogicType } from './saveToCohortModalContentLogicType'

const COHORTS_PER_PAGE = 100

interface CohortFilters {
    search?: string
    page?: number
    type: string
}

const DEFAULT_COHORT_FILTERS: CohortFilters = {
    search: undefined,
    page: 1,
    type: 'static',
}

export const saveToCohortModalContentLogic = kea<saveToCohortModalContentLogicType>([
    path(['lib', 'components', 'SaveToCohortModal', 'saveToCohortModalContentLogic']),
    actions({
        setCohortFilters: (filters: Partial<CohortFilters>) => ({ filters }),
    }),
    reducers({
        cohorts: [{ count: 0, results: [] }],
        cohortFilters: [
            DEFAULT_COHORT_FILTERS,
            {
                setCohortFilters: (state, { filters }) => {
                    return { ...state, ...filters }
                },
            },
        ],
    }),
    loaders(({ values }) => ({
        cohorts: {
            __default: { count: 0, results: [] } as CountedPaginatedResponse<CohortType>,
            loadCohorts: async () => {
                const response = await api.cohorts.listPaginated({
                    ...values.paramsFromFilters,
                })
                return {
                    count: response.count,
                    results: response.results,
                }
            },
        },
    })),
    selectors(({ actions }) => ({
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
                    onBackward: () => actions.setCohortFilters({ page: filters.page - 1 }),
                    onForward: () => actions.setCohortFilters({ page: filters.page + 1 }),
                }
            },
        ],
    })),
    listeners(({ actions }) => ({
        setCohortFilters: async () => {
            actions.loadCohorts()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadCohorts()
    }),
])
