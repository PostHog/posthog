import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { PaginationManual, lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { delay } from 'lib/utils'
import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { ActorsQuery } from '~/queries/schema/schema-general'
import { CohortType } from '~/types'

import type { saveToCohortModalContentLogicType } from './saveToCohortModalContentLogicType'

const COHORTS_PER_PAGE = 100

export interface CohortFilters {
    search?: string
    page?: number
    type: 'static' | 'dynamic'
}

const DEFAULT_COHORT_FILTERS: CohortFilters = {
    search: undefined,
    page: 1,
    type: 'static',
}

export const saveToCohortModalContentLogic = kea<saveToCohortModalContentLogicType>([
    path(['lib', 'components', 'SaveToCohortModal', 'saveToCohortModalContentLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        setCohortFilters: (filters: Partial<CohortFilters>) => ({ filters }),
        saveQueryToCohort: (cohort: CohortType, query: ActorsQuery) => ({ cohort, query }),
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
                    onBackward: () => actions.setCohortFilters({ page: filters.page != null ? filters.page - 1 : 1 }),
                    onForward: () => actions.setCohortFilters({ page: filters.page != null ? filters.page + 1 : 1 }),
                }
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        setCohortFilters: async () => {
            actions.loadCohorts()
        },
        saveQueryToCohort: async ({ cohort, query }) => {
            const toastId = `save-cohort-${cohort.id}-${Date.now()}`
            try {
                lemonToast.info('Saving cohort...', { toastId, autoClose: false })
                await api.update(`api/projects/${values.currentProjectId}/cohorts/${cohort.id}`, {
                    query: query,
                })

                const mountedCohortEditLogic = cohortEditLogic.findMounted({ id: cohort.id })
                await mountedCohortEditLogic?.actions.updateCohortCount()

                await delay(500) // just in case the toast is too fast
                lemonToast.dismiss(toastId)
                lemonToast.success('Cohort saved', {
                    toastId: `${toastId}-success`,
                    button: {
                        label: 'View cohort',
                        action: () => router.actions.push(urls.cohort(cohort.id)),
                    },
                })
            } catch (error) {
                console.error('Save to cohort failed:', error)
                lemonToast.dismiss(toastId)
                lemonToast.error('Save to cohort failed')
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadCohorts()
    }),
])
