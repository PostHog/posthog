import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { projectLogic } from 'scenes/projectLogic'

import { FeatureFlagType } from '~/types'

import { featureFlagsLogic } from './featureFlagsLogic'
import type { flagSelectionLogicType } from './flagSelectionLogicType'

export interface BulkDeleteResult {
    deleted: Array<{ id: number; key: string }>
    errors: Array<{ id: number; key?: string; reason: string }>
}

export const flagSelectionLogic = kea<flagSelectionLogicType>([
    path(['scenes', 'feature-flags', 'flagSelectionLogic']),

    connect(() => ({
        values: [projectLogic, ['currentProjectId'], featureFlagsLogic({}), ['displayedFlags']],
        actions: [featureFlagsLogic({}), ['loadFeatureFlags']],
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
                if (flags.length === 0) {
                    return false
                }
                const flagIds = flags.map((f) => f.id).filter((id: number | null): id is number => id !== null)
                return flagIds.every((id) => selectedIds.includes(id))
            },
        ],
        isSomeSelected: [
            (s) => [s.selectedFlagIds, s.displayedFlags],
            (selectedIds: number[], flags: FeatureFlagType[]) => {
                const flagIds = flags.map((f) => f.id).filter((id: number | null): id is number => id !== null)
                return (
                    flagIds.some((id) => selectedIds.includes(id)) && !flagIds.every((id) => selectedIds.includes(id))
                )
            },
        ],
        resultsModalVisible: [(s) => [s.bulkDeleteResult], (result: BulkDeleteResult | null) => result !== null],
    }),

    listeners(({ values, actions }) => ({
        toggleFlagSelection: ({ id, index }) => {
            const { selectedFlagIds, shiftKeyHeld, previouslyCheckedIndex, displayedFlags } = values

            if (shiftKeyHeld && previouslyCheckedIndex !== null) {
                // Shift-click: select range
                const start = Math.min(previouslyCheckedIndex, index)
                const end = Math.max(previouslyCheckedIndex, index)
                const flagsInRange = displayedFlags
                    .slice(start, end + 1)
                    .map((f: FeatureFlagType) => f.id)
                    .filter((id: number | null): id is number => id !== null)

                // Add all flags in range to selection
                const newSelection = [...new Set([...selectedFlagIds, ...flagsInRange])]
                actions.setSelectedFlagIds(newSelection)
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
                .map((f: FeatureFlagType) => f.id)
                .filter((id: number | null): id is number => id !== null)
            actions.setSelectedFlagIds(flagIds)
        },
        bulkDeleteFlagsSuccess: ({ bulkDeleteResponse }) => {
            if (bulkDeleteResponse) {
                actions.showResultsModal(bulkDeleteResponse)
                actions.clearSelection()
                actions.loadFeatureFlags()
            }
        },
    })),

    afterMount(({ actions }) => {
        const onKeyChange = (event: KeyboardEvent): void => {
            actions.setShiftKeyHeld(event.shiftKey)
        }

        // Register shift key listener
        window.addEventListener('keydown', onKeyChange)
        window.addEventListener('keyup', onKeyChange)

        // Return cleanup function that will be called on unmount
        return () => {
            window.removeEventListener('keydown', onKeyChange)
            window.removeEventListener('keyup', onKeyChange)
        }
    }),
])
