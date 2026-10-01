import type { TodayWorkSectionId } from './todaySpacesLogic'
import type { TodayWorkItem } from './todayWorkItems'

/** The ids picked for a bulk action, and the row a Shift-click range starts from. */
export interface TodaySessionSelection {
    ids: string[]
    anchorId: string | null
}

export type TodaySelectionClick = 'toggle' | 'range' | 'open'

export const EMPTY_SELECTION: TodaySessionSelection = { ids: [], anchorId: null }

export function selectionClick(event: Pick<MouseEvent, 'shiftKey' | 'metaKey' | 'ctrlKey'>): TodaySelectionClick {
    return event.shiftKey ? 'range' : event.metaKey || event.ctrlKey ? 'toggle' : 'open'
}

/** Pinned first, then Recent, skipping chats and any collapsed section, like the rows on screen. */
export function orderedVisibleSessionIds(
    pinned: TodayWorkItem[],
    recent: TodayWorkItem[],
    collapsedSections: TodayWorkSectionId[]
): string[] {
    return [
        ...(collapsedSections.includes('pinned') ? [] : pinned),
        ...(collapsedSections.includes('recent') ? [] : recent),
    ]
        .filter((item) => item.kind === 'session')
        .map((item) => item.id)
}

export function toggleSelection(selection: TodaySessionSelection, id: string): TodaySessionSelection {
    return {
        ids: selection.ids.includes(id) ? selection.ids.filter((selected) => selected !== id) : [...selection.ids, id],
        anchorId: id,
    }
}

/** Adds the rows from the anchor to `toId` and keeps the rest of the selection, like Shift-click in Desktop. */
export function computeRangeSelection(
    anchorId: string | null,
    toId: string,
    orderedIds: string[],
    current: string[]
): TodaySessionSelection {
    const anchorIndex = anchorId ? orderedIds.indexOf(anchorId) : -1
    const toIndex = orderedIds.indexOf(toId)
    if (anchorIndex === -1 || toIndex === -1) {
        return { ids: [toId], anchorId: toId }
    }
    const range = orderedIds.slice(Math.min(anchorIndex, toIndex), Math.max(anchorIndex, toIndex) + 1)
    return { ids: Array.from(new Set([...current, ...range])), anchorId: toId }
}

export function pruneToVisible(ids: string[], visibleIds: string[]): string[] {
    const visible = new Set(visibleIds)
    return ids.filter((id) => visible.has(id))
}
