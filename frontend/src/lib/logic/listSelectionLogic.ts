import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { projectLogic } from 'scenes/projectLogic'

import { tagsModel } from '~/models/tagsModel'

import type { listSelectionLogicType } from './listSelectionLogicType'

export type BulkTagAction = 'add' | 'remove' | 'set'

export interface BulkUpdateTagsResult {
    updated: Array<{ id: number; tags: string[] }>
    skipped: Array<{ id: number; reason: string }>
}

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

    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),

    actions({
        setSelectedIds: (ids: number[]) => ({ ids }),
        toggleSelection: (id: number, index: number, allPageItems: PageItem[]) => ({ id, index, allPageItems }),
        selectAllOnPage: (allPageItems: PageItem[]) => ({ allPageItems }),
        clearSelection: true,
        setShiftKeyHeld: (shiftKeyHeld: boolean) => ({ shiftKeyHeld }),
        setPreviouslyCheckedIndex: (index: number | null) => ({ index }),
        showBulkTagsPopover: true,
        hideBulkTagsPopover: true,
        setPopoverTagAction: (tagAction: BulkTagAction) => ({ tagAction }),
        setPopoverSelectedTags: (tags: string[]) => ({ tags }),
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
        bulkTagsPopoverVisible: [
            false as boolean,
            {
                showBulkTagsPopover: () => true,
                hideBulkTagsPopover: () => false,
                clearSelection: () => false,
            },
        ],
        popoverTagAction: [
            'add' as BulkTagAction,
            {
                setPopoverTagAction: (_, { tagAction }) => tagAction,
                hideBulkTagsPopover: () => 'add',
            },
        ],
        popoverSelectedTags: [
            [] as string[],
            {
                setPopoverSelectedTags: (_, { tags }) => tags,
                hideBulkTagsPopover: () => [],
            },
        ],
    }),

    loaders(({ values, props: logicProps }) => ({
        bulkUpdateTagsResponse: [
            null as BulkUpdateTagsResult | null,
            {
                bulkUpdateTags: async ({ action, tags }: { action: BulkTagAction; tags: string[] }) => {
                    const response = await api.create(
                        `api/projects/${values.currentProjectId}/${logicProps.resource}/bulk_update_tags/`,
                        { ids: values.selectedIds, action, tags }
                    )
                    return response as BulkUpdateTagsResult
                },
            },
        ],
    })),

    selectors({
        selectedCount: [(s) => [s.selectedIds], (ids: number[]) => ids.length],
        selectedIdsSet: [(s) => [s.selectedIds], (ids: number[]) => new Set(ids)],
    }),

    listeners(({ values, actions }) => ({
        showBulkTagsPopover: () => {
            tagsModel.actions.loadTags()
        },

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

        bulkUpdateTagsSuccess: ({ bulkUpdateTagsResponse }) => {
            if (bulkUpdateTagsResponse) {
                const { updated, skipped } = bulkUpdateTagsResponse
                if (skipped.length === 0) {
                    lemonToast.success(`Updated tags on ${updated.length} item${updated.length !== 1 ? 's' : ''}`)
                } else {
                    lemonToast.warning(
                        `Updated tags on ${updated.length} item${updated.length !== 1 ? 's' : ''}. ${skipped.length} skipped due to permissions.`
                    )
                }
                actions.hideBulkTagsPopover()
                actions.clearSelection()
                tagsModel.actions.loadTags()
            }
        },

        bulkUpdateTagsFailure: () => {
            lemonToast.error('Failed to update tags')
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
