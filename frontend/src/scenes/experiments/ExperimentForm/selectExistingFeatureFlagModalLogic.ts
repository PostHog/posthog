import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { PaginationManual } from '@posthog/lemon-ui'

import api from 'lib/api'
import { toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { FLAGS_PER_PAGE } from 'scenes/feature-flags/featureFlagsLogic'
import { teamLogic } from 'scenes/teamLogic'

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

    connect({
        actions: [
            eventUsageLogic,
            ['reportExperimentFeatureFlagModalOpened'],
            teamLogic,
            ['loadCurrentTeamSuccess', 'updateCurrentTeamSuccess'],
        ],
        values: [teamLogic, ['currentTeam']],
    }),

    actions({
        openSelectExistingFeatureFlagModal: true,
        closeSelectExistingFeatureFlagModal: true,
        setFilters: (filters: Partial<FeatureFlagModalFilters>, replace?: boolean) => ({ filters, replace }),
        resetFilters: true,
        loadFeatureFlagsForAutocomplete: true,
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

    listeners(({ actions, values }) => ({
        setFilters: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadFeatureFlags()
        },
        resetFilters: () => {
            actions.loadFeatureFlags()
        },
        openSelectExistingFeatureFlagModal: () => {
            actions.reportExperimentFeatureFlagModalOpened()
            actions.loadFeatureFlags()
        },
        loadFeatureFlagsForAutocomplete: () => {
            actions.loadFeatureFlags()
        },
        loadCurrentTeamSuccess: () => {
            if (values.isModalOpen) {
                actions.loadFeatureFlags()
            }
        },
        updateCurrentTeamSuccess: () => {
            if (values.isModalOpen) {
                actions.loadFeatureFlags()
            }
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
            (s) => [s.filters, s.currentTeam],
            (filters: FeatureFlagModalFilters, currentTeam) => {
                const params: Record<string, any> = {
                    ...filters,
                    limit: FLAGS_PER_PAGE,
                    offset: filters.page ? (filters.page - 1) * FLAGS_PER_PAGE : 0,
                }

                // Add evaluation tags filter if required by team
                if (currentTeam?.require_evaluation_contexts) {
                    params.has_evaluation_tags = true
                }

                return params
            },
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
        isEvaluationTagsRequired: [
            (s) => [s.currentTeam],
            (currentTeam) => currentTeam?.require_evaluation_contexts || false,
        ],
    }),
])
