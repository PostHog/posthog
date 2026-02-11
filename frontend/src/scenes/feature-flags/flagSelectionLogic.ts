import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'

import api from 'lib/api'
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

export const flagSelectionLogic = kea<flagSelectionLogicType>([
    path(['scenes', 'feature-flags', 'flagSelectionLogic']),

    connect(() => ({
        values: [
            projectLogic,
            ['currentProjectId'],
            featureFlagsLogic({}),
            ['displayedFlags', 'count', 'paramsFromFilters'],
        ],
        actions: [featureFlagsLogic({}), ['loadFeatureFlags']],
    })),

    actions({
        setSelectedFlagIds: (ids: number[]) => ({ ids }),
        toggleFlagSelection: (id: number, index: number) => ({ id, index }),
        selectAll: true,
        selectAllMatching: true,
        clearSelection: true,
        setShiftKeyHeld: (shiftKeyHeld: boolean) => ({ shiftKeyHeld }),
        setPreviouslyCheckedIndex: (index: number | null) => ({ index }),
        showResultsModal: (result: BulkDeleteResult) => ({ result }),
        hideResultsModal: true,
        setAllMatchingSelected: (allMatchingSelected: boolean) => ({ allMatchingSelected }),
    }),

    reducers({
        selectedFlagIds: [
            [] as number[],
            {
                setSelectedFlagIds: (_, { ids }) => ids,
                clearSelection: () => [],
            },
        ],
        shiftKeyHeld: [
            false as boolean,
            {
                setShiftKeyHeld: (_, { shiftKeyHeld }) => shiftKeyHeld,
            },
        ],
        previouslyCheckedIndex: [
            null as number | null,
            {
                setPreviouslyCheckedIndex: (_, { index }) => index,
                clearSelection: () => null,
            },
        ],
        bulkDeleteResult: [
            null as BulkDeleteResult | null,
            {
                showResultsModal: (_, { result }) => result,
                hideResultsModal: () => null,
            },
        ],
        // Tracks whether "select all matching" mode is active
        allMatchingSelected: [
            false as boolean,
            {
                setAllMatchingSelected: (_, { allMatchingSelected }) => allMatchingSelected,
                clearSelection: () => false,
                // When manually toggling selection, exit "all matching" mode
                toggleFlagSelection: () => false,
                selectAll: () => false,
            },
        ],
    }),

    loaders(({ values }) => ({
        matchingFlagIds: [
            null as { ids: number[]; total: number } | null,
            {
                loadMatchingFlagIds: async () => {
                    // Build query params matching the current filters (without pagination)
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
                        // Use filter-based deletion - backend handles all matching flags
                        const { limit, offset, ...filters } = paramsFromFilters
                        const response = await api.create(
                            `api/projects/${currentProjectId}/feature_flags/bulk_delete/`,
                            { filters }
                        )
                        return response as BulkDeleteResult
                    }

                    // Use ID-based deletion (explicit selection)
                    const response = await api.create(`api/projects/${currentProjectId}/feature_flags/bulk_delete/`, {
                        ids: selectedFlagIds,
                    })
                    return response as BulkDeleteResult
                },
            },
        ],
    })),

    selectors({
        selectedCount: [(s) => [s.selectedFlagIds], (ids: number[]) => ids.length],
        isAllSelected: [
            (s) => [s.selectedFlagIds, s.displayedFlags],
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
            (s) => [s.selectedFlagIds, s.displayedFlags],
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
        // Show the "select all matching" banner when all page items are selected
        // and there are more flags matching the filter than currently displayed
        showSelectAllMatchingBanner: [
            (s) => [s.isAllSelected, s.displayedFlags, s.count, s.allMatchingSelected],
            (
                isAllSelected: boolean,
                displayedFlags: FeatureFlagType[],
                totalCount: number,
                allMatchingSelected: boolean
            ) => {
                if (allMatchingSelected) {
                    return false // Already selected all matching
                }
                const editableOnPage = displayedFlags.filter((f) => f.can_edit).length
                // Show banner if all on page are selected and there are more flags than the page size
                return isAllSelected && editableOnPage > 0 && totalCount > FLAGS_PER_PAGE
            },
        ],
        // Total matching count for the banner
        totalMatchingCount: [(s) => [s.count], (count: number) => count],
    }),

    listeners(({ values, actions }) => ({
        toggleFlagSelection: ({ id, index }) => {
            const { selectedFlagIds, shiftKeyHeld, previouslyCheckedIndex, displayedFlags } = values

            if (shiftKeyHeld && previouslyCheckedIndex !== null) {
                // Shift-click: select range, following the anchor's direction
                const start = Math.min(previouslyCheckedIndex, index)
                const end = Math.max(previouslyCheckedIndex, index)
                const flagIdsInRange = displayedFlags
                    .slice(start, end + 1)
                    .filter((f: FeatureFlagType) => f.can_edit)
                    .map((f: FeatureFlagType) => f.id)
                    .filter((fid: number | null): fid is number => fid !== null)

                // Determine direction from anchor: if the clicked flag was already selected,
                // we're deselecting the range; otherwise we're selecting it
                const isDeselecting = selectedFlagIds.includes(id)
                if (isDeselecting) {
                    const rangeSet = new Set(flagIdsInRange)
                    actions.setSelectedFlagIds(selectedFlagIds.filter((fid: number) => !rangeSet.has(fid)))
                } else {
                    actions.setSelectedFlagIds([...new Set([...selectedFlagIds, ...flagIdsInRange])])
                }
            } else {
                // Normal click: toggle single flag
                const isSelected = selectedFlagIds.includes(id)
                if (isSelected) {
                    actions.setSelectedFlagIds(selectedFlagIds.filter((fid: number) => fid !== id))
                } else {
                    actions.setSelectedFlagIds([...selectedFlagIds, id])
                }
            }

            actions.setPreviouslyCheckedIndex(index)
        },
        selectAll: () => {
            const flagIds = values.displayedFlags
                .filter((f: FeatureFlagType) => f.can_edit)
                .map((f: FeatureFlagType) => f.id)
                .filter((id: number | null): id is number => id !== null)
            actions.setSelectedFlagIds(flagIds)
        },
        selectAllMatching: () => {
            // Fetch all matching IDs from the backend
            actions.loadMatchingFlagIds()
        },
        loadMatchingFlagIdsSuccess: ({ matchingFlagIds }) => {
            if (matchingFlagIds) {
                actions.setSelectedFlagIds(matchingFlagIds.ids)
                actions.setAllMatchingSelected(true)
            }
        },
        loadMatchingFlagIdsFailure: () => {
            // Reset to page-only selection on failure
            actions.setAllMatchingSelected(false)
        },
        // Note: Selection is intentionally preserved across filter/pagination changes
        // to allow users to select flags across multiple pages. Use clearSelection to reset.
        bulkDeleteFlagsSuccess: ({ bulkDeleteResponse }) => {
            if (bulkDeleteResponse) {
                actions.showResultsModal(bulkDeleteResponse)
                actions.clearSelection()
                actions.loadFeatureFlags()
            }
        },
    })),

    // Warn user if they try to leave during bulk deletion
    beforeUnload(({ values }) => ({
        enabled: () => values.bulkDeleteResponseLoading,
        message: 'Bulk delete is in progress. Leaving may result in incomplete deletion.',
    })),

    afterMount(({ actions, cache }) => {
        cache.disposables.add(() => {
            const onKeyChange = (event: KeyboardEvent): void => {
                actions.setShiftKeyHeld(event.shiftKey)
            }
            window.addEventListener('keydown', onKeyChange)
            window.addEventListener('keyup', onKeyChange)
            return () => {
                window.removeEventListener('keydown', onKeyChange)
                window.removeEventListener('keyup', onKeyChange)
            }
        }, 'shiftKeyListener')
    }),
])
