import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'

import api from 'lib/api'
import { listSelectionLogic } from 'lib/logic/listSelectionLogic'
import { toParams } from 'lib/utils'
import { projectLogic } from 'scenes/projectLogic'

import { FeatureFlagType } from '~/types'

import { FLAGS_PER_PAGE, featureFlagsLogic } from './featureFlagsLogic'
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

const selectionLogic = listSelectionLogic({ resource: 'feature_flags' })

export const flagSelectionLogic = kea<flagSelectionLogicType>([
    path(['scenes', 'feature-flags', 'flagSelectionLogic']),

    connect(() => ({
        values: [
            projectLogic,
            ['currentProjectId'],
            featureFlagsLogic({}),
            ['featureFlags', 'count', 'paramsFromFilters', 'displayedFlags'],
            selectionLogic,
            ['selectedIds as selectedFlagIds', 'selectedCount'],
        ],
        actions: [
            featureFlagsLogic({}),
            ['loadFeatureFlags'],
            selectionLogic,
            [
                'setSelectedIds as setSelectedFlagIds',
                'toggleSelection as toggleFlagSelection',
                'selectAllOnPage',
                'clearSelection',
            ],
        ],
    })),

    actions({
        selectAllMatching: true,
        showResultsModal: (result: BulkDeleteResult) => ({ result }),
        hideResultsModal: true,
        setAllMatchingSelected: (allMatchingSelected: boolean) => ({ allMatchingSelected }),
    }),

    reducers({
        bulkDeleteResult: [
            null as BulkDeleteResult | null,
            {
                showResultsModal: (_, { result }) => result,
                hideResultsModal: () => null,
            },
        ],
        allMatchingSelected: [
            false as boolean,
            {
                setAllMatchingSelected: (_, { allMatchingSelected }) => allMatchingSelected,
                clearSelection: () => false,
                toggleFlagSelection: () => false,
                selectAllOnPage: () => false,
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
                bulkDeleteFlags: async () => {
                    const { allMatchingSelected, selectedFlagIds, paramsFromFilters, currentProjectId } = values

                    if (allMatchingSelected) {
                        const { limit, offset, ...filters } = paramsFromFilters
                        const response = await api.create(
                            `api/projects/${currentProjectId}/feature_flags/bulk_delete/`,
                            { filters }
                        )
                        return response as BulkDeleteResult
                    }

                    const response = await api.create(`api/projects/${currentProjectId}/feature_flags/bulk_delete/`, {
                        ids: selectedFlagIds,
                    })
                    return response as BulkDeleteResult
                },
            },
        ],
    })),

    selectors({
        currentPageFlags: [(s) => [s.featureFlags], (featureFlags): FeatureFlagType[] => featureFlags?.results || []],
        isAllSelected: [
            (s) => [s.selectedFlagIds, s.currentPageFlags],
            (selectedIds: number[], flags: FeatureFlagType[]) => {
                const editableIds = flags
                    .filter((f) => f.can_edit)
                    .map((f) => f.id)
                    .filter((id: number | null): id is number => id !== null)
                if (editableIds.length === 0) {
                    return false
                }
                return editableIds.every((id) => selectedIds.includes(id))
            },
        ],
        isSomeSelected: [
            (s) => [s.selectedFlagIds, s.currentPageFlags],
            (selectedIds: number[], flags: FeatureFlagType[]) => {
                const editableIds = flags
                    .filter((f) => f.can_edit)
                    .map((f) => f.id)
                    .filter((id: number | null): id is number => id !== null)
                return (
                    editableIds.some((id) => selectedIds.includes(id)) &&
                    !editableIds.every((id) => selectedIds.includes(id))
                )
            },
        ],
        resultsModalVisible: [(s) => [s.bulkDeleteResult], (result: BulkDeleteResult | null) => result !== null],
        showSelectAllMatchingBanner: [
            (s) => [s.selectedCount, s.count, s.allMatchingSelected],
            (selectedCount: number, totalCount: number, allMatchingSelected: boolean) => {
                if (allMatchingSelected) {
                    return false
                }
                return selectedCount >= FLAGS_PER_PAGE && totalCount > selectedCount
            },
        ],
        totalMatchingCount: [(s) => [s.count], (count: number) => count],
    }),

    listeners(({ actions }) => ({
        selectAllMatching: () => {
            actions.loadMatchingFlagIds()
        },
        loadMatchingFlagIdsSuccess: ({ matchingFlagIds }) => {
            if (matchingFlagIds) {
                actions.setSelectedFlagIds(matchingFlagIds.ids)
                actions.setAllMatchingSelected(true)
            }
        },
        loadMatchingFlagIdsFailure: () => {
            actions.setAllMatchingSelected(false)
        },
        bulkDeleteFlagsSuccess: ({ bulkDeleteResponse }) => {
            if (bulkDeleteResponse) {
                actions.showResultsModal(bulkDeleteResponse)
                actions.clearSelection()
                actions.loadFeatureFlags()
            }
        },
    })),

    beforeUnload(({ values }) => ({
        enabled: () => values.bulkDeleteResponseLoading,
        message: 'Bulk delete is in progress. Leaving may result in incomplete deletion.',
    })),
])
