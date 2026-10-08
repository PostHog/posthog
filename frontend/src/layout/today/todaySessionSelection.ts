import type { TodayWorkSectionId } from './todaySpacesLogic'
import type { TodayWorkItem } from './todayWorkItems'

/** The ids picked for a bulk action, and the row a Shift-click range starts from. */
export interface TodaySessionSelection {
    ids: string[]
    anchorId: string | null
}

export type TodaySelectionClick = 'toggle' | 'range' | 'open'

export type TodayBulkVerb = 'pin' | 'unpin' | 'file' | 'archive' | 'restore'

const PAST_TENSE: Record<TodayBulkVerb, string> = {
    pin: 'pinned',
    unpin: 'unpinned',
    file: 'filed',
    archive: 'archived',
    restore: 'restored',
}

export const EMPTY_SELECTION: TodaySessionSelection = { ids: [], anchorId: null }

export function isEditableTarget(target: EventTarget | null): boolean {
    return (
        target instanceof HTMLElement &&
        (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
    )
}

/** Base UI prevents the default of the Escape that closes a menu, so that press only closes the menu. */
export function isMenuEscape(event: KeyboardEvent): boolean {
    return (
        event.defaultPrevented ||
        (event.target instanceof Element && event.target.closest('[role="menu"][data-open]') !== null)
    )
}

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

/** Like Desktop, a right-click on a row inside a selection acts on the selection, not on that one row. */
export function rightClickActsOnSelection(selectedIds: string[], sessionId: string): boolean {
    return selectedIds.length > 1 && selectedIds.includes(sessionId)
}

export function pruneToVisible(ids: string[], visibleIds: string[]): string[] {
    const visible = new Set(visibleIds)
    return ids.filter((id) => visible.has(id))
}

/** Pinning wins a mixed selection, so the group ends up in one section instead of split across two. */
export function computeBulkPinDirection(ids: string[], pinnedIds: ReadonlySet<string>): 'pin' | 'unpin' {
    return ids.length > 0 && ids.every((id) => pinnedIds.has(id)) ? 'unpin' : 'pin'
}

export function sessionsLabel(count: number): string {
    return `${count} ${count === 1 ? 'session' : 'sessions'}`
}

export function bulkArchiveWarning(count: number, running: number): string {
    const who =
        running === count
            ? `${count === 1 ? 'This session is' : `These ${count} sessions are`} still running.`
            : `${running} of these ${count} sessions ${running === 1 ? 'is' : 'are'} still running.`
    const what =
        running === 1
            ? 'Archiving it will stop its cloud run and shut down the sandbox.'
            : 'Archiving them will stop their cloud runs and shut down the sandboxes.'
    return `${who} ${what} You can unarchive them later.`
}

export function bulkResultToast(
    verb: TodayBulkVerb,
    succeeded: number,
    failed: number
): { kind: 'success' | 'error'; title: string; description?: string } {
    if (failed === 0) {
        return { kind: 'success', title: `${sessionsLabel(succeeded)} ${PAST_TENSE[verb]}` }
    }
    return {
        kind: 'error',
        title: `Couldn’t ${verb} ${failed} of ${sessionsLabel(succeeded + failed)}`,
        description: verb === 'restore' ? 'Try again.' : 'They’re still selected, so you can try again.',
    }
}
