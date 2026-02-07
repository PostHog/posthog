import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { projectLogic } from 'scenes/projectLogic'

import { FeatureFlagType } from '~/types'

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
        values: [projectLogic, ['currentProjectId'], featureFlagsLogic({}), ['displayedFlags']],
        actions: [featureFlagsLogic({}), ['loadFeatureFlags', 'setFeatureFlagsFilters']],
    })),

    actions({
        setSelectedFlagIds: (ids: number[]) => ({ ids }),
        toggleFlagSelection: (id: number, index: number) => ({ id, index }),
        selectAll: true,
        clearSelection: true,
        setShiftKeyHeld: (shiftKeyHeld: boolean) => ({ shiftKeyHeld }),
        setPreviouslyCheckedIndex: (index: number | null) => ({ index }),
        showResultsModal: (result: BulkDeleteResult) => ({ result }),
        hideResultsModal: true,
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
    }),

    loaders(({ values }) => ({
        bulkDeleteResponse: [
            null as BulkDeleteResult | null,
            {
                bulkDeleteFlags: async () => {
                    const response = await api.create(
                        `api/projects/${values.currentProjectId}/feature_flags/bulk_delete/`,
                        { ids: values.selectedFlagIds }
                    )
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
        setFeatureFlagsFilters: () => {
            actions.clearSelection()
        },
        bulkDeleteFlagsSuccess: ({ bulkDeleteResponse }) => {
            if (bulkDeleteResponse) {
                actions.showResultsModal(bulkDeleteResponse)
                actions.clearSelection()
                actions.loadFeatureFlags()
            }
        },
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
