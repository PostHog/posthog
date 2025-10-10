import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { PaginationManual } from '@posthog/lemon-ui'

import api from 'lib/api'
import { toParams } from 'lib/utils'
import { FLAGS_PER_PAGE } from 'scenes/feature-flags/featureFlagsLogic'

import { FeatureFlagType } from '~/types'

import type { selectExistingFeatureFlagModalLogicType } from './selectExistingFeatureFlagModalLogicType'

export interface FeatureFlagModalFilters {
    active?: string
    created_by_id?: number
    search?: string
    order?: string
    page?: number
    evaluation_runtime?: string
}

const DEFAULT_FILTERS: FeatureFlagModalFilters = {
    active: undefined,
    created_by_id: undefined,
    search: undefined,
    order: undefined,
    page: 1,
    evaluation_runtime: undefined,
}

export const selectExistingFeatureFlagModalLogic = kea<selectExistingFeatureFlagModalLogicType>([
    path(['scenes', 'experiments', 'create', 'selectExistingFeatureFlagModalLogic']),

    actions({
        openSelectExistingFeatureFlagModal: true,
        closeSelectExistingFeatureFlagModal: true,
        setFilters: (filters: Partial<FeatureFlagModalFilters>, replace?: boolean) => ({ filters, replace }),
        resetFilters: true,
    }),

    reducers({
        isModalOpen: [
            false,
            {
                openSelectExistingFeatureFlagModal: () => true,
                closeSelectExistingFeatureFlagModal: () => false,
            },
        ],
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters, replace }) => {
                    if (replace) {
                        return { ...DEFAULT_FILTERS, ...filters }
                    }
                    return { ...state, ...filters }
                },
                resetFilters: () => DEFAULT_FILTERS,
            },
        ],
    }),

    listeners(({ actions }) => ({
        setFilters: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadFeatureFlags()
        },
        resetFilters: () => {
            actions.loadFeatureFlags()
        },
        openSelectExistingFeatureFlagModal: () => {
            actions.loadFeatureFlags()
        },
    })),

    loaders(({ values }) => ({
        featureFlags: [
            { results: [], count: 0 } as { results: FeatureFlagType[]; count: number },
            {
                loadFeatureFlags: async () => {
                    const url = `api/projects/@current/experiments/eligible_feature_flags/?${toParams({
                        ...values.paramsFromFilters,
                    })}`
                    const response = await api.get(url)
                    return response
                },
            },
        ],
    })),

    selectors({
        paramsFromFilters: [
            (s) => [s.filters],
            (filters: FeatureFlagModalFilters) => ({
                ...filters,
                limit: FLAGS_PER_PAGE,
                offset: filters.page ? (filters.page - 1) * FLAGS_PER_PAGE : 0,
            }),
        ],
        pagination: [
            (s) => [s.filters, s.featureFlags],
            (filters, featureFlags): PaginationManual => {
                const currentPage = filters.page || 1
                const hasNextPage = featureFlags.count > currentPage * FLAGS_PER_PAGE
                const hasPreviousPage = currentPage > 1
                const needsPagination = featureFlags.count > FLAGS_PER_PAGE

                return {
                    controlled: true,
                    pageSize: FLAGS_PER_PAGE,
                    currentPage,
                    entryCount: featureFlags.count,
                    onForward:
                        needsPagination && hasNextPage
                            ? () => {
                                  selectExistingFeatureFlagModalLogic.actions.setFilters({ page: currentPage + 1 })
                              }
                            : undefined,
                    onBackward:
                        needsPagination && hasPreviousPage
                            ? () => {
                                  selectExistingFeatureFlagModalLogic.actions.setFilters({
                                      page: Math.max(1, currentPage - 1),
                                  })
                              }
                            : undefined,
                }
            },
        ],
    }),
])
