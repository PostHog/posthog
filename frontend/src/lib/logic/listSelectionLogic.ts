import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { listSelectionLogicType } from './listSelectionLogicType'

export type BulkTaggableResource = 'feature_flags' | 'dashboards' | 'insights'

export interface PageItem {
    id: number
    isEditable: boolean
}

export interface ListSelectionLogicProps {
    resource: BulkTaggableResource
}

/**
 * Compute whether all/some editable items on the current page are selected.
 * Exported as a helper so each scene can call it with its own displayed items
 * without the shared logic needing to know about the item type.
 */
export function getSelectionState(
    selectedIds: number[],
    editableIds: number[]
): { isAllSelected: boolean; isSomeSelected: boolean } {
    if (editableIds.length === 0) {
        return { isAllSelected: false, isSomeSelected: false }
    }
    const selectedSet = new Set(selectedIds)
    const allSelected = editableIds.every((id) => selectedSet.has(id))
    const someSelected = editableIds.some((id) => selectedSet.has(id)) && !allSelected
    return { isAllSelected: allSelected, isSomeSelected: someSelected }
}

export const listSelectionLogic = kea<listSelectionLogicType>([
    path((key) => ['lib', 'logic', 'listSelectionLogic', key]),
    props({} as ListSelectionLogicProps),
    key(({ resource }) => resource),

    actions({
        setSelectedIds: (ids: number[]) => ({ ids }),
        toggleSelection: (id: number, index: number, allPageItems: PageItem[]) => ({ id, index, allPageItems }),
        selectAllOnPage: (allPageItems: PageItem[]) => ({ allPageItems }),
        clearSelection: true,
        setShiftKeyHeld: (shiftKeyHeld: boolean) => ({ shiftKeyHeld }),
        setPreviouslyCheckedIndex: (index: number | null) => ({ index }),
    }),

    reducers({
        selectedIds: [
            [] as number[],
            {
                setSelectedIds: (_, { ids }) => ids,
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
    }),

    selectors({
        selectedCount: [(s) => [s.selectedIds], (ids: number[]) => ids.length],
        selectedIdsSet: [(s) => [s.selectedIds], (ids: number[]) => new Set(ids)],
    }),

    listeners(({ values, actions }) => ({
        toggleSelection: ({ id, index, allPageItems }) => {
            const { selectedIds, shiftKeyHeld, previouslyCheckedIndex } = values

            if (shiftKeyHeld && previouslyCheckedIndex !== null) {
                const start = Math.min(previouslyCheckedIndex, index)
                const end = Math.max(previouslyCheckedIndex, index)
                const idsInRange = allPageItems
                    .slice(start, end + 1)
                    .filter((item) => item.isEditable)
                    .map((item) => item.id)

                const isDeselecting = selectedIds.includes(id)
                if (isDeselecting) {
                    const rangeSet = new Set(idsInRange)
                    actions.setSelectedIds(selectedIds.filter((sid) => !rangeSet.has(sid)))
                } else {
                    actions.setSelectedIds([...new Set([...selectedIds, ...idsInRange])])
                }
            } else {
                const isSelected = selectedIds.includes(id)
                if (isSelected) {
                    actions.setSelectedIds(selectedIds.filter((sid) => sid !== id))
                } else {
                    actions.setSelectedIds([...selectedIds, id])
                }
            }

            actions.setPreviouslyCheckedIndex(index)
        },

        selectAllOnPage: ({ allPageItems }) => {
            const editableIds = allPageItems.filter((item) => item.isEditable).map((item) => item.id)
            const { selectedIds } = values
            const selectedSet = new Set(selectedIds)
            const allSelected = editableIds.length > 0 && editableIds.every((id) => selectedSet.has(id))

            if (allSelected) {
                const pageIdSet = new Set(editableIds)
                actions.setSelectedIds(selectedIds.filter((id) => !pageIdSet.has(id)))
            } else {
                actions.setSelectedIds([...new Set([...selectedIds, ...editableIds])])
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
