import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'

import api from 'lib/api'
import { toParams } from 'lib/utils'
import { projectLogic } from 'scenes/projectLogic'

import { featureFlagsLogic } from './featureFlagsLogic'
import type { flagSelectionLogicType } from './flagSelectionLogicType'

export type FlagRolloutState = 'fully_rolled_out' | 'not_rolled_out' | 'partial'

export interface DeletedFlagInfo {
    id: number
    key: string
    rollout_state: FlagRolloutState
    active_variant: string | null
}

export interface BulkDeleteResult {
    deleted: DeletedFlagInfo[]
    errors: Array<{ id: number; key?: string; reason: string }>
}

export const flagSelectionLogic = kea<flagSelectionLogicType>([
    path(['scenes', 'feature-flags', 'flagSelectionLogic']),

    connect(() => ({
        values: [projectLogic, ['currentProjectId'], featureFlagsLogic({}), ['paramsFromFilters']],
        actions: [featureFlagsLogic({}), ['loadFeatureFlags']],
    })),

    actions({
        showResultsModal: (result: BulkDeleteResult) => ({ result }),
        hideResultsModal: true,
    }),

    reducers({
        bulkDeleteResult: [
            null as BulkDeleteResult | null,
            {
                showResultsModal: (_, { result }) => result,
                hideResultsModal: () => null,
            },
        ],
    }),

    loaders(({ values }) => ({
        matchingFlagIds: [
            null as { ids: number[]; total: number } | null,
            {
                loadMatchingFlagIds: async () => {
                    const { limit, offset, ...filters } = values.paramsFromFilters
                    const response = await api.get(
                        `api/projects/${values.currentProjectId}/feature_flags/matching_ids/?${toParams(filters)}`
                    )
                    return response as { ids: number[]; total: number }
                },
            },
        ],
        bulkDeleteResponse: [
            null as BulkDeleteResult | null,
            {
                bulkDeleteFlags: async ({ ids, allMatching }: { ids: number[]; allMatching: boolean }) => {
                    if (allMatching) {
                        const { limit, offset, ...filters } = values.paramsFromFilters
                        const response = await api.create(
                            `api/projects/${values.currentProjectId}/feature_flags/bulk_delete/`,
                            { filters }
                        )
                        return response as BulkDeleteResult
                    }
                    const response = await api.create(
                        `api/projects/${values.currentProjectId}/feature_flags/bulk_delete/`,
                        { ids }
                    )
                    return response as BulkDeleteResult
                },
            },
        ],
    })),

    selectors({
        resultsModalVisible: [(s) => [s.bulkDeleteResult], (result: BulkDeleteResult | null) => result !== null],
    }),

    listeners(({ actions }) => ({
        bulkDeleteFlagsSuccess: ({ bulkDeleteResponse }) => {
            if (bulkDeleteResponse) {
                actions.showResultsModal(bulkDeleteResponse)
                actions.loadFeatureFlags()
            }
        },
    })),

    beforeUnload(({ values }) => ({
        enabled: () => values.bulkDeleteResponseLoading,
        message: 'Bulk delete is in progress. Leaving may result in incomplete deletion.',
    })),
])
